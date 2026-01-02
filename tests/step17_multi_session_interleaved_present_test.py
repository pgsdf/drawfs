#!/usr/bin/env python3
import os
import struct
import errno
import fcntl
import mmap
import select
import time

DEV = "/dev/draw"

DRAWFS_MAGIC = 0x31575244
DRAWFS_VERSION = 0x0100

# Request message types
REQ_HELLO = 0x0001
REQ_DISPLAY_LIST = 0x0010
REQ_DISPLAY_OPEN = 0x0011
REQ_SURFACE_CREATE = 0x0020
REQ_SURFACE_PRESENT = 0x0022

# Reply message types
RPL_HELLO = 0x8001
RPL_DISPLAY_LIST = 0x8010
RPL_DISPLAY_OPEN = 0x8011
RPL_SURFACE_CREATE = 0x8020
RPL_SURFACE_PRESENT = 0x8022

# Event message types
EVT_SURFACE_PRESENTED = 0x9002

# Formats used by the wire protocol
fh_fmt = "<IHHII"   # magic, version, header_bytes, frame_bytes, frame_id
mh_fmt = "<HHIII"   # msg_type, msg_flags, msg_bytes, msg_id, reserved

# Surface formats (must match kernel protocol)
FMT_XRGB8888 = 1

# ioctl helpers (must match sys/dev/drawfs/drawfs_ioctl.h)
IOC_INOUT = 0xC0000000
def _IOC(inout, group, num, length):
    return inout | ((length & 0x1FFF) << 16) | ((group & 0xFF) << 8) | (num & 0xFF)

def _IOWR(group_chr, num, length):
    return _IOC(IOC_INOUT, ord(group_chr), num, length)

MAP_REP_FMT = "<iIII"  # status, surface_id, stride, total
MAP_REP_SIZE = struct.calcsize(MAP_REP_FMT)
DRAWFSGIOC_MAP_SURFACE = _IOWR("D", 0x02, MAP_REP_SIZE)

def align4(n: int) -> int:
    return (n + 3) & ~3

def make_msg(msg_type: int, msg_id: int, payload: bytes) -> bytes:
    payload = payload or b""
    msg_bytes = align4(struct.calcsize(mh_fmt) + len(payload))
    msg_hdr = struct.pack(mh_fmt, msg_type, 0, msg_bytes, msg_id, 0)
    msg = msg_hdr + payload
    if len(msg) < msg_bytes:
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
    if len(frame) < frame_bytes:
        frame += b"\x00" * (frame_bytes - len(frame))
    return frame

def read_one_message(buf: bytes, off: int):
    if off + struct.calcsize(mh_fmt) > len(buf):
        return None
    msg_type, msg_flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    if msg_bytes < struct.calcsize(mh_fmt):
        return None
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off + payload_len]
    return (msg_type, msg_id, payload, msg_bytes)

def read_frame(fd: int, want_timeout_ms: int = 1000):
    r, _, _ = select.select([fd], [], [], want_timeout_ms / 1000.0)
    if not r:
        raise TimeoutError("timeout waiting for reply/event frame")
    buf = os.read(fd, 4096)
    if len(buf) < struct.calcsize(fh_fmt):
        raise RuntimeError("short read for frame header")
    magic, ver, header_bytes, frame_bytes, frame_id = struct.unpack_from(fh_fmt, buf, 0)
    if magic != DRAWFS_MAGIC:
        raise RuntimeError(f"bad magic 0x{magic:x}")
    if ver != DRAWFS_VERSION:
        raise RuntimeError(f"bad version 0x{ver:x}")
    if header_bytes != struct.calcsize(fh_fmt):
        raise RuntimeError(f"bad header_bytes {header_bytes}")
    return buf, frame_id

def read_first_message(fd: int, timeout_ms: int = 1000):
    buf, _fid = read_frame(fd, timeout_ms)
    off = struct.calcsize(fh_fmt)
    m = read_one_message(buf, off)
    if not m:
        raise RuntimeError("failed to parse first message in frame")
    msg_type, msg_id, payload, _msg_bytes = m
    return msg_type, msg_id, payload

def wait_for_msg_type(fd: int, want_type: int, timeout_ms: int = 1000):
    deadline = time.time() + (timeout_ms / 1000.0)
    while True:
        remain = deadline - time.time()
        if remain <= 0:
            raise TimeoutError(f"timeout waiting for msg_type 0x{want_type:x}")
        buf, _fid = read_frame(fd, int(remain * 1000))
        off = struct.calcsize(fh_fmt)
        # Walk all messages in the frame
        while off + struct.calcsize(mh_fmt) <= len(buf):
            m = read_one_message(buf, off)
            if not m:
                break
            msg_type, msg_id, payload, msg_bytes = m
            if msg_type == want_type:
                return msg_type, msg_id, payload
            off += align4(msg_bytes)

def hello(fd: int, frame_id: int, msg_id: int):
    # <HHII>: major, minor, flags, max_frame_bytes
    payload = struct.pack("<HHII", 1, 0, 0, 65536)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_HELLO, msg_id, payload)]))
    _t, _mid, _pl = read_first_message(fd, 1000)

def display_list(fd: int, frame_id: int, msg_id: int):
    os.write(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_LIST, msg_id, b"")]))
    msg_type, _mid, pl = read_first_message(fd, 1000)
    if msg_type != RPL_DISPLAY_LIST:
        raise RuntimeError(f"expected DISPLAY_LIST reply, got 0x{msg_type:x}")

    # Reply payload: uint32 count followed by entries.
    # Entry format in earlier steps: id(uint32), w(uint32), h(uint32), refresh_mhz(uint32), flags(uint32)
    if len(pl) < 4:
        raise RuntimeError("short DISPLAY_LIST payload")
    (count,) = struct.unpack_from("<I", pl, 0)
    off = 4
    displays = []
    for _ in range(count):
        if off + 20 > len(pl):
            break
        did, w, h, refresh, flags = struct.unpack_from("<IIIII", pl, off)
        displays.append((did, w, h, refresh, flags))
        off += 20
    return displays

def display_open(fd: int, frame_id: int, msg_id: int, display_id: int):
    payload = struct.pack("<I", display_id)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_OPEN, msg_id, payload)]))
    msg_type, _mid, pl = read_first_message(fd, 1000)
    if msg_type != RPL_DISPLAY_OPEN:
        raise RuntimeError(f"expected DISPLAY_OPEN reply, got 0x{msg_type:x}")
    # status(int32), handle(uint32), active_id(uint32)
    if len(pl) < 12:
        raise RuntimeError("short DISPLAY_OPEN payload")
    status, handle, active_id = struct.unpack_from("<iII", pl, 0)
    return status, handle, active_id

def surface_create(fd: int, frame_id: int, msg_id: int, width: int, height: int, fmt: int):
    # req: width(uint32), height(uint32), fmt(uint32), flags(uint32)
    payload = struct.pack("<IIII", width, height, fmt, 0)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_CREATE, msg_id, payload)]))
    msg_type, _mid, pl = read_first_message(fd, 1000)
    if msg_type != RPL_SURFACE_CREATE:
        raise RuntimeError(f"expected SURFACE_CREATE reply, got 0x{msg_type:x}")
    # rep: status(int32), surface_id(uint32), stride(uint32), total(uint32)
    if len(pl) < 16:
        raise RuntimeError("short SURFACE_CREATE payload")
    status, sid, stride, total = struct.unpack_from("<iIII", pl, 0)
    return status, sid, stride, total

def map_surface_ioctl(fd: int, surface_id: int):
    buf = bytearray(MAP_REP_SIZE)
    # Kernel expects struct with req then rep in one object.
    # Our ioctl struct is { req{surface_id}, rep{status,surface_id,stride,total} } in the kernel header.
    # For compatibility with earlier steps, we write surface_id at offset 4 (after int32 status)
    struct.pack_into("<iI", buf, 0, 0, surface_id)
    try:
        fcntl.ioctl(fd, DRAWFSGIOC_MAP_SURFACE, buf, True)
    except OSError as e:
        if e.errno == errno.ENOTTY:
            return (errno.ENOTTY, 0, 0, 0)
        raise
    return struct.unpack_from(MAP_REP_FMT, buf, 0)

def surface_present(fd: int, frame_id: int, msg_id: int, surface_id: int, cookie: int):
    # req: surface_id(uint32), flags(uint32), cookie(uint64)
    payload = struct.pack("<IIQ", surface_id, 0, cookie)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_PRESENT, msg_id, payload)]))
    msg_type, _mid, pl = read_first_message(fd, 1000)
    if msg_type != RPL_SURFACE_PRESENT:
        raise RuntimeError(f"expected SURFACE_PRESENT reply, got 0x{msg_type:x}")
    # rep: status(int32), surface_id(uint32), cookie(uint64)
    if len(pl) < 16:
        # older variant: status only
        if len(pl) >= 4:
            (status,) = struct.unpack_from("<i", pl, 0)
            return status, 0, 0
        raise RuntimeError("short SURFACE_PRESENT reply payload")
    status, sid, cookie_ret = struct.unpack_from("<iIQ", pl, 0)
    return status, sid, cookie_ret

def decode_surface_presented_event(payload: bytes):
    """
    Event payload can vary slightly depending on which version you have in the tree.
    Supported layouts:
      <IQ>     (12 bytes): surface_id, cookie
      <IIQ>    (16 bytes): surface_id, flags, cookie
    If payload is larger, we decode the leading bytes and ignore the rest.
    """
    if len(payload) >= 16:
        sid, flags, cookie = struct.unpack_from("<IIQ", payload, 0)
        return sid, flags, cookie
    if len(payload) >= 12:
        sid, cookie = struct.unpack_from("<IQ", payload, 0)
        return sid, 0, cookie
    raise RuntimeError(f"short SURFACE_PRESENTED event payload len={len(payload)}")

def main():
    fd1 = os.open(DEV, os.O_RDWR)
    fd2 = os.open(DEV, os.O_RDWR)

    try:
        # Bring up both sessions
        hello(fd1, frame_id=1, msg_id=1)
        hello(fd2, frame_id=2, msg_id=2)

        # DISPLAY_LIST and DISPLAY_OPEN on both fds
        d1 = display_list(fd1, frame_id=3, msg_id=3)
        d2 = display_list(fd2, frame_id=4, msg_id=4)

        if not d1 or not d2:
            raise RuntimeError("no displays reported")

        display_id = d1[0][0]
        st1, _h1, _a1 = display_open(fd1, frame_id=5, msg_id=5, display_id=display_id)
        st2, _h2, _a2 = display_open(fd2, frame_id=6, msg_id=6, display_id=display_id)
        if st1 != 0 or st2 != 0:
            raise RuntimeError(f"DISPLAY_OPEN failed st1={st1} st2={st2}")

        # Create one surface per session
        st, sid1, stride1, total1 = surface_create(fd1, frame_id=7, msg_id=7, width=256, height=256, fmt=FMT_XRGB8888)
        if st != 0:
            raise RuntimeError(f"SURFACE_CREATE fd1 status={st}")
        st, sid2, stride2, total2 = surface_create(fd2, frame_id=8, msg_id=8, width=256, height=256, fmt=FMT_XRGB8888)
        if st != 0:
            raise RuntimeError(f"SURFACE_CREATE fd2 status={st}")

        # Try MAP_SURFACE on each fd and, if available, mmap and write a tiny pattern
        rep1 = map_surface_ioctl(fd1, sid1)
        if rep1[0] == errno.ENOTTY:
            print("NOTE: MAP_SURFACE ioctl not available for fd1 (ENOTTY), continuing")
        else:
            if rep1[0] != 0:
                raise RuntimeError(f"MAP_SURFACE fd1 status={rep1[0]}")
            mm1 = mmap.mmap(fd1, rep1[3], mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
            try:
                mm1[:64] = b"\xff\xff\xff\x00" * 16
                mm1.flush()
            finally:
                mm1.close()

        rep2 = map_surface_ioctl(fd2, sid2)
        if rep2[0] == errno.ENOTTY:
            print("NOTE: MAP_SURFACE ioctl not available for fd2 (ENOTTY), continuing")
        else:
            if rep2[0] != 0:
                raise RuntimeError(f"MAP_SURFACE fd2 status={rep2[0]}")
            mm2 = mmap.mmap(fd2, rep2[3], mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
            try:
                mm2[:64] = b"\x00\x00\xff\x00" * 16
                mm2.flush()
            finally:
                mm2.close()

        # Interleaved present
        cookie1 = 0x1111111111111111
        cookie2 = 0x2222222222222222

        st, _sid_ret, _cookie_ret = surface_present(fd1, frame_id=9, msg_id=9, surface_id=sid1, cookie=cookie1)
        if st != 0:
            raise RuntimeError(f"SURFACE_PRESENT fd1 status={st}")

        st, _sid_ret, _cookie_ret = surface_present(fd2, frame_id=10, msg_id=10, surface_id=sid2, cookie=cookie2)
        if st != 0:
            raise RuntimeError(f"SURFACE_PRESENT fd2 status={st}")

        # Wait for SURFACE_PRESENTED on each fd, validate isolation
        t1, _mid1, evpl1 = wait_for_msg_type(fd1, EVT_SURFACE_PRESENTED, timeout_ms=2000)
        sid_ev1, flags_ev1, cookie_ev1 = decode_surface_presented_event(evpl1)

        t2, _mid2, evpl2 = wait_for_msg_type(fd2, EVT_SURFACE_PRESENTED, timeout_ms=2000)
        sid_ev2, flags_ev2, cookie_ev2 = decode_surface_presented_event(evpl2)

        # Debug, helpful when things drift
        # print("DEBUG sid1:", sid1, "sid2:", sid2)
        # print("DEBUG ev1:", hex(t1), len(evpl1), evpl1.hex(), sid_ev1, flags_ev1, hex(cookie_ev1))
        # print("DEBUG ev2:", hex(t2), len(evpl2), evpl2.hex(), sid_ev2, flags_ev2, hex(cookie_ev2))

        assert sid_ev1 == sid1
        assert cookie_ev1 == cookie1
        assert sid_ev2 == sid2
        assert cookie_ev2 == cookie2

        print("OK: Step 17 multi session interleaved present passed")

    finally:
        os.close(fd1)
        os.close(fd2)

if __name__ == "__main__":
    main()

