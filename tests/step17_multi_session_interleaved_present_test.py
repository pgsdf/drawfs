#!/usr/bin/env python3
import os, struct, errno, fcntl, mmap, select, time

DEV = "/dev/draw"
DRAWFS_MAGIC   = 0x31575244  # 'DRW1'
DRAWFS_VERSION = 0x0100      # 1.0

# Requests
REQ_HELLO          = 0x0001
REQ_DISPLAY_OPEN   = 0x0011
REQ_SURFACE_CREATE = 0x0020
REQ_SURFACE_PRESENT= 0x0022

# Replies and events
RPL_SURFACE_CREATE  = 0x8020
RPL_DISPLAY_OPEN    = 0x8011
RPL_SURFACE_PRESENT = 0x8022
EVT_SURFACE_PRESENTED = 0x9002

# Wire formats
fh_fmt = "<IHHII"
mh_fmt = "<HHIII"

def align4(n: int) -> int:
    return (n + 3) & ~3

def make_msg(msg_type: int, msg_id: int, payload: bytes) -> bytes:
    payload = payload or b""
    msg_bytes = align4(struct.calcsize(mh_fmt) + len(payload))
    msg_hdr = struct.pack(mh_fmt, msg_type, 0, msg_bytes, msg_id, 0)
    msg = msg_hdr + payload
    msg += b"\x00" * (msg_bytes - len(msg))
    return msg

def make_frame(frame_id: int, msgs: list[bytes]) -> bytes:
    body = b"".join(msgs)
    frame_bytes = align4(struct.calcsize(fh_fmt) + len(body))
    frame_hdr = struct.pack(fh_fmt, DRAWFS_MAGIC, DRAWFS_VERSION,
                            struct.calcsize(fh_fmt), frame_bytes, frame_id)
    frame = frame_hdr + body
    frame += b"\x00" * (frame_bytes - len(frame))
    return frame

def read_one(fd):
    buf = os.read(fd, 4096)
    if len(buf) < struct.calcsize(fh_fmt) + struct.calcsize(mh_fmt):
        raise RuntimeError("short read")
    off = struct.calcsize(fh_fmt)
    msg_type, _flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off + payload_len]
    return msg_type, msg_id, payload

# ioctl helpers (must match sys/dev/drawfs/drawfs_ioctl.h)
IOC_INOUT = 0xC0000000
def _IOC(inout, group, num, length):
    return inout | ((length & 0x1fff) << 16) | ((group & 0xff) << 8) | (num & 0xff)
def _IOWR(group_chr, num, length):
    return _IOC(IOC_INOUT, ord(group_chr), num, length)

MAP_REP_FMT = "<iIII"
MAP_REP_SIZE = struct.calcsize(MAP_REP_FMT)
DRAWFSGIOC_MAP_SURFACE = _IOWR('D', 0x02, MAP_REP_SIZE)

def map_surface_ioctl(fd, surface_id: int):
    buf = bytearray(MAP_REP_SIZE)
    struct.pack_into("<iI", buf, 0, 0, surface_id)  # status, surface_id
    fcntl.ioctl(fd, DRAWFSGIOC_MAP_SURFACE, buf, True)
    return struct.unpack_from(MAP_REP_FMT, buf, 0)

def handshake(fd, frame_base: int, msg_base: int):
    hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
    os.write(fd, make_frame(frame_base, [make_msg(REQ_HELLO, msg_base, hello_payload)]))
    _ = os.read(fd, 4096)


def hello(fd, frame_id: int, msg_id: int):
    """Compatibility alias used by earlier steps."""
    handshake(fd, frame_id, msg_id)

def display_open(fd, frame_id: int, msg_id: int, display_id: int = 1):
    open_payload = struct.pack("<I", display_id)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_OPEN, msg_id, open_payload)]))
    msg_type, _mid, payload = read_one(fd)
    if msg_type != RPL_DISPLAY_OPEN:
        raise RuntimeError(f"expected DISPLAY_OPEN reply, got 0x{msg_type:x}")
    status, handle, active_id = struct.unpack_from("<iII", payload, 0)
    if status != 0:
        raise RuntimeError(f"DISPLAY_OPEN status={status}")
    return handle

def surface_create(fd, frame_id: int, msg_id: int, w: int, h: int, fmt: int = 1):
    # req: <IIII> width height format flags
    sc_req = struct.pack("<IIII", w, h, fmt, 0)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_CREATE, msg_id, sc_req)]))
    msg_type, _mid, payload = read_one(fd)
    if msg_type != RPL_SURFACE_CREATE:
        raise RuntimeError(f"expected SURFACE_CREATE reply, got 0x{msg_type:x}")
    status, sid, stride, total = struct.unpack_from("<iIII", payload, 0)
    if status != 0:
        raise RuntimeError(f"SURFACE_CREATE status={status}")
    return sid, stride, total

def surface_present(fd, frame_id: int, msg_id: int, surface_id: int, cookie: int):
    # req: <IQ> surface_id, cookie
    # Kernel expects: uint32 surface_id, uint32 reserved, uint64 cookie
    req = struct.pack("<IIQ", surface_id, 0, cookie)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_PRESENT, msg_id, req)]))
    msg_type, _mid, payload = read_one(fd)
    if msg_type != RPL_SURFACE_PRESENT:
        raise RuntimeError(f"expected SURFACE_PRESENT reply, got 0x{msg_type:x}")
    status, = struct.unpack_from("<i", payload, 0)
    if status != 0:
        raise RuntimeError(f"SURFACE_PRESENT status={status}")

def wait_presented(fd, timeout_ms: int = 1000):
    p = select.poll()
    p.register(fd, select.POLLIN | select.POLLRDNORM)
    ev = p.poll(timeout_ms)
    if not ev:
        raise RuntimeError("timeout waiting for event")
    msg_type, _mid, payload = read_one(fd)
    if msg_type != EVT_SURFACE_PRESENTED:
        raise RuntimeError(f"expected SURFACE_PRESENTED (0x9002), got 0x{msg_type:x}")
    surface_id, flags, cookie = struct.unpack_from("<IIQ", payload, 0)
    return surface_id, flags, cookie

def main():
    # Two independent sessions (two fds) must not leak state:
    # - surface ids are per session
    # - MAP_SURFACE selection is per session
    # - events must be delivered only to the fd that generated them
    fd1 = os.open(DEV, os.O_RDWR)
    fd2 = os.open(DEV, os.O_RDWR)
    try:
        # Session 1 init
        hello(fd1, frame_id=1, msg_id=1)
        display_open(fd1, frame_id=2, msg_id=2, display_id=1)

        # Session 2 init
        hello(fd2, frame_id=10, msg_id=10)
        display_open(fd2, frame_id=11, msg_id=11, display_id=1)

        # Create one surface per session
        sid1, stride1, total1 = surface_create(fd1, frame_id=3, msg_id=3, width=256, height=256, fmt=FMT_XRGB8888)
        sid2, stride2, total2 = surface_create(fd2, frame_id=12, msg_id=12, width=256, height=256, fmt=FMT_XRGB8888)

        # Map each surface and paint a unique pattern
        st, msid1, mstride1, mtotal1 = map_surface_ioctl(fd1, sid1)
        assert st == 0 and msid1 == sid1 and mstride1 == stride1 and mtotal1 == total1

        st, msid2, mstride2, mtotal2 = map_surface_ioctl(fd2, sid2)
        assert st == 0 and msid2 == sid2 and mstride2 == stride2 and mtotal2 == total2

        mm1 = mmap.mmap(fd1, total1, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        mm2 = mmap.mmap(fd2, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            # Session 1: white
            mm1[:64] = b"\xff\xff\xff\x00" * 16
            mm1.flush()

            # Session 2: greenish (XRGB, B G R 0 in little endian for 0x00RRGGBB layout in memory)
            mm2[:64] = b"\x00\xff\x00\x00" * 16
            mm2.flush()

            # Interleaved presents, verify isolation via cookie
            cookie1a = 0x1111111111111111
            cookie2a = 0x2222222222222222
            surface_present(fd1, frame_id=4, msg_id=4, surface_id=sid1, cookie=cookie1a)
            surface_present(fd2, frame_id=13, msg_id=13, surface_id=sid2, cookie=cookie2a)

            psid1, _flags1, pcookie1 = wait_presented(fd1, timeout_ms=1000)
            assert psid1 == sid1 and pcookie1 == cookie1a

            psid2, _flags2, pcookie2 = wait_presented(fd2, timeout_ms=1000)
            assert psid2 == sid2 and pcookie2 == cookie2a

            # Second round, reverse order
            cookie1b = 0xaaaaaaaaaaaaaaaa
            cookie2b = 0xbbbbbbbbbbbbbbbb
            surface_present(fd2, frame_id=14, msg_id=14, surface_id=sid2, cookie=cookie2b)
            surface_present(fd1, frame_id=5, msg_id=5, surface_id=sid1, cookie=cookie1b)

            psid2, _flags2, pcookie2 = wait_presented(fd2, timeout_ms=1000)
            assert psid2 == sid2 and pcookie2 == cookie2b

            psid1, _flags1, pcookie1 = wait_presented(fd1, timeout_ms=1000)
            assert psid1 == sid1 and pcookie1 == cookie1b

        finally:
            mm1.close()
            mm2.close()

        # Close session 1, session 2 must continue to function
        os.close(fd1)
        fd1 = -1

        # Re-map and present again on fd2 after the other session is gone
        st, msid2, mstride2, mtotal2 = map_surface_ioctl(fd2, sid2)
        assert st == 0 and msid2 == sid2

        mm2 = mmap.mmap(fd2, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            mm2[:64] = b"\x00\x00\xff\x00" * 16  # red-ish
            mm2.flush()

            cookie2c = 0xcccccccccccccccc
            surface_present(fd2, frame_id=15, msg_id=15, surface_id=sid2, cookie=cookie2c)

            psid2, _flags2, pcookie2 = wait_presented(fd2, timeout_ms=1000)
            assert psid2 == sid2 and pcookie2 == cookie2c
        finally:
            mm2.close()

        print("OK: Step 17 multi session interleaved present passed")

    finally:
        if fd1 != -1:
            os.close(fd1)
        os.close(fd2)

if __name__ == "__main__":
    main()