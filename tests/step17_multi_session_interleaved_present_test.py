#!/usr/bin/env python3
import os
import struct
import select
import errno

DEV = "/dev/draw"

# Protocol constants
DRAWFS_MAGIC   = 0x31575244  # 'DRW1'
DRAWFS_VERSION = 0x0100

# Request types
REQ_HELLO           = 0x0001
REQ_DISPLAY_LIST    = 0x0010
REQ_DISPLAY_OPEN    = 0x0011
REQ_SURFACE_CREATE  = 0x0020
REQ_SURFACE_PRESENT = 0x0022

# Reply types
RPL_OK              = 0x8001
RPL_DISPLAY_LIST    = 0x8010
RPL_DISPLAY_OPEN    = 0x8011
RPL_SURFACE_CREATE  = 0x8020
RPL_SURFACE_PRESENT = 0x8022

# Event types
EVT_SURFACE_PRESENTED = 0x9002

# Pixel formats
FMT_XRGB8888 = 1

# Wire formats
fh_fmt = "<IHHII"   # magic, version, header_bytes, frame_bytes, frame_id
mh_fmt = "<HHIII"   # msg_type, flags, msg_bytes, msg_id, reserved

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
    frame_hdr = struct.pack(
        fh_fmt,
        DRAWFS_MAGIC,
        DRAWFS_VERSION,
        struct.calcsize(fh_fmt),
        frame_bytes,
        frame_id,
    )
    frame = frame_hdr + body
    frame += b"\x00" * (frame_bytes - len(frame))
    return frame

def read_one_message(fd: int, timeout_ms: int = 1000):
    """
    Read a single frame from fd and return (msg_type, msg_id, payload_bytes).
    Assumes one message per reply/event frame (as used by these tests).
    """
    p = select.poll()
    p.register(fd, select.POLLIN | select.POLLRDNORM)
    ev = p.poll(timeout_ms)
    if not ev:
        raise RuntimeError("timeout waiting for readable")

    buf = os.read(fd, 8192)
    if len(buf) < struct.calcsize(fh_fmt) + struct.calcsize(mh_fmt):
        raise RuntimeError(f"short read: {len(buf)} bytes")

    off = struct.calcsize(fh_fmt)
    msg_type, _msg_flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off + payload_len]
    return msg_type, msg_id, payload

def hello(fd: int, frame_id: int, msg_id: int):
    """
    Send HELLO.
    Payload: <HHII> (major, minor, flags, max_msg_bytes)
    """
    hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_HELLO, msg_id, hello_payload)]))

    msg_type, _mid, _pl = read_one_message(fd, 1000)
    if msg_type != RPL_OK:
        raise RuntimeError(f"HELLO expected RPL_OK (0x8001), got 0x{msg_type:x}")

def display_list(fd: int, frame_id: int, msg_id: int):
    os.write(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_LIST, msg_id, b"")]))
    msg_type, _mid, pl = read_one_message(fd, 1000)
    if msg_type != RPL_DISPLAY_LIST:
        raise RuntimeError(f"DISPLAY_LIST expected 0x8010, got 0x{msg_type:x}")

    # <I count> then count * <I id, I width, I height, I refresh_mhz, I flags>
    if len(pl) < 4:
        raise RuntimeError("DISPLAY_LIST payload too short")
    count = struct.unpack_from("<I", pl, 0)[0]
    displays = []
    off = 4
    for _ in range(count):
        if off + 20 > len(pl):
            raise RuntimeError("DISPLAY_LIST payload truncated")
        did, w, h, refresh, flags = struct.unpack_from("<IIIII", pl, off)
        displays.append((did, w, h, refresh, flags))
        off += 20
    return displays

def display_open(fd: int, frame_id: int, msg_id: int, display_id: int):
    payload = struct.pack("<I", display_id)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_OPEN, msg_id, payload)]))
    msg_type, _mid, pl = read_one_message(fd, 1000)
    if msg_type != RPL_DISPLAY_OPEN:
        raise RuntimeError(f"DISPLAY_OPEN expected 0x8011, got 0x{msg_type:x}")

    # <i status, I handle, I active_display_id>
    if len(pl) < 12:
        raise RuntimeError("DISPLAY_OPEN payload too short")
    status, handle, active_id = struct.unpack_from("<iII", pl, 0)
    if status != 0:
        raise RuntimeError(f"DISPLAY_OPEN status={status}")
    return handle, active_id

def surface_create(fd: int, frame_id: int, msg_id: int, width: int, height: int, fmt: int):
    # <I width, I height, I format, I flags>
    payload = struct.pack("<IIII", width, height, fmt, 0)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_CREATE, msg_id, payload)]))
    msg_type, _mid, pl = read_one_message(fd, 1000)
    if msg_type != RPL_SURFACE_CREATE:
        raise RuntimeError(f"SURFACE_CREATE expected 0x8020, got 0x{msg_type:x}")

    # <i status, I surface_id, I stride, I total>
    if len(pl) < 16:
        raise RuntimeError("SURFACE_CREATE payload too short")
    status, sid, stride, total = struct.unpack_from("<iIII", pl, 0)
    if status != 0:
        raise RuntimeError(f"SURFACE_CREATE status={status}")
    return sid, stride, total

def map_surface_ioctl(fd: int, surface_id: int):
    """
    Optional sanity check.
    If the ioctl code does not match the running kernel module, FreeBSD returns ENOTTY (Errno 25).
    """
    import fcntl

    # struct drawfs_map_surface is typically 20 bytes: req u32 + rep (i32 + 3*u32)
    buf = bytearray(4 + 16)
    struct.pack_into("<I", buf, 0, surface_id)

    IOC_INOUT = 0xC0000000
    def _IOC(inout, group, num, length):
        return inout | ((length & 0x1fff) << 16) | ((group & 0xff) << 8) | (num & 0xff)
    def _IOWR(group_chr, num, length):
        return _IOC(IOC_INOUT, ord(group_chr), num, length)

    DRAWFSGIOC_MAP_SURFACE = _IOWR('D', 0x02, len(buf))
    fcntl.ioctl(fd, DRAWFSGIOC_MAP_SURFACE, buf, True)

    status, sid, stride, total = struct.unpack_from("<iIII", buf, 4)
    return status, sid, stride, total

def surface_present(fd: int, frame_id: int, msg_id: int, surface_id: int, cookie: int):
    # <I surface_id, I flags, Q cookie>
    payload = struct.pack("<IIQ", surface_id, 0, cookie)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_PRESENT, msg_id, payload)]))
    msg_type, _mid, pl = read_one_message(fd, 1000)
    if msg_type != RPL_SURFACE_PRESENT:
        raise RuntimeError(f"SURFACE_PRESENT expected 0x8022, got 0x{msg_type:x}")
    if len(pl) < 4:
        raise RuntimeError("SURFACE_PRESENT payload too short")
    status = struct.unpack_from("<i", pl, 0)[0]
    if status != 0:
        raise RuntimeError(f"SURFACE_PRESENT status={status}")

def wait_presented(fd: int, timeout_ms: int = 1000):
    msg_type, _mid, pl = read_one_message(fd, timeout_ms)
    if msg_type != EVT_SURFACE_PRESENTED:
        raise RuntimeError(f"expected SURFACE_PRESENTED (0x9002), got 0x{msg_type:x}")
    if len(pl) < 16:
        raise RuntimeError("SURFACE_PRESENTED payload too short")
    sid, flags, cookie = struct.unpack_from("<IIQ", pl, 0)
    return sid, flags, cookie

def try_map_surface(fd: int, sid: int, label: str):
    try:
        st, msid, mstride, mtotal = map_surface_ioctl(fd, sid)
        if st != 0:
            raise RuntimeError(f"MAP_SURFACE({label}) status={st}")
        return (st, msid, mstride, mtotal)
    except OSError as e:
        if e.errno == errno.ENOTTY:
            # ioctl code mismatch or not supported in this build
            print(f"NOTE: MAP_SURFACE ioctl not available for {label} (ENOTTY), continuing")
            return None
        raise

def main():
    fd1 = os.open(DEV, os.O_RDWR)
    fd2 = os.open(DEV, os.O_RDWR)
    try:
        # Session 1 init
        hello(fd1, frame_id=1, msg_id=1)
        d1 = display_list(fd1, frame_id=2, msg_id=2)
        if not d1:
            raise RuntimeError("no displays")
        display_id1 = d1[0][0]
        display_open(fd1, frame_id=3, msg_id=3, display_id=display_id1)

        # Session 2 init
        hello(fd2, frame_id=11, msg_id=11)
        d2 = display_list(fd2, frame_id=12, msg_id=12)
        if not d2:
            raise RuntimeError("no displays")
        display_id2 = d2[0][0]
        display_open(fd2, frame_id=13, msg_id=13, display_id=display_id2)

        # Create surfaces, one per session
        sid1, _stride1, _total1 = surface_create(
            fd1, frame_id=4, msg_id=4, width=256, height=256, fmt=FMT_XRGB8888
        )
        sid2, _stride2, _total2 = surface_create(
            fd2, frame_id=14, msg_id=14, width=256, height=256, fmt=FMT_XRGB8888
        )

        # Optional sanity checks
        try_map_surface(fd1, sid1, "fd1")
        try_map_surface(fd2, sid2, "fd2")

        # Interleaved presents
        cookie1a = 0xAAAABBBBCCCCDDDD
        cookie2a = 0x1111222233334444
        cookie1b = 0xDEADBEEF00000001
        cookie2b = 0xDEADBEEF00000002

        surface_present(fd1, frame_id=5,  msg_id=5,  surface_id=sid1, cookie=cookie1a)
        surface_present(fd2, frame_id=15, msg_id=15, surface_id=sid2, cookie=cookie2a)

        psid, _flags, pcookie = wait_presented(fd1, 1000)
        assert psid == sid1 and pcookie == cookie1a
        psid, _flags, pcookie = wait_presented(fd2, 1000)
        assert psid == sid2 and pcookie == cookie2a

        surface_present(fd2, frame_id=16, msg_id=16, surface_id=sid2, cookie=cookie2b)
        surface_present(fd1, frame_id=6,  msg_id=6,  surface_id=sid1, cookie=cookie1b)

        psid, _flags, pcookie = wait_presented(fd2, 1000)
        assert psid == sid2 and pcookie == cookie2b
        psid, _flags, pcookie = wait_presented(fd1, 1000)
        assert psid == sid1 and pcookie == cookie1b

        print("OK: Step 17 multi session interleaved present passed")
    finally:
        os.close(fd2)
        os.close(fd1)

if __name__ == "__main__":
    main()

