#!/usr/bin/env python3

"""Step 15: session cleanup and reopen.

Validate that drawfs session state is per open file descriptor.

Sequence
  1. open /dev/draw
  2. HELLO, DISPLAY_OPEN
  3. SURFACE_CREATE -> MAP_SURFACE -> mmap write -> SURFACE_PRESENT
  4. close fd
  5. reopen /dev/draw
  6. HELLO, DISPLAY_OPEN
  7. MAP_SURFACE(old_surface_id) must fail (ENOENT or EINVAL)
  8. SURFACE_CREATE must return surface_id == 1 (fresh session)
"""

import errno
import fcntl
import mmap
import os
import struct

DEV = "/dev/draw"

DRAWFS_MAGIC = 0x31575244
DRAWFS_VERSION = 0x0100

# Requests
REQ_HELLO = 0x0001
REQ_DISPLAY_OPEN = 0x0011
REQ_SURFACE_CREATE = 0x0020
REQ_SURFACE_PRESENT = 0x0022

# Replies / events
RPL_SURFACE_CREATE = 0x8020
RPL_SURFACE_PRESENT = 0x8022
EVT_SURFACE_PRESENTED = 0x9022

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


def read_one(fd):
    buf = os.read(fd, 4096)
    off = struct.calcsize(fh_fmt)
    msg_type, _msg_flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off : payload_off + payload_len]
    return msg_type, msg_id, payload


def decode_surface_create(payload: bytes):
    # <iIII => status, surface_id, stride, total
    return struct.unpack_from("<iIII", payload, 0)


def decode_surface_present_reply(payload: bytes):
    # <iIQ => status, surface_id, cookie
    return struct.unpack_from("<iIQ", payload, 0)


def decode_surface_presented_event(payload: bytes):
    # <IIQ => surface_id, flags, cookie
    return struct.unpack_from("<IIQ", payload, 0)


# ioctl helpers
IOC_INOUT = 0xC0000000


def _IOC(inout, group, num, length):
    return inout | ((length & 0x1FFF) << 16) | ((group & 0xFF) << 8) | (num & 0xFF)


def _IOWR(group_chr, num, length):
    return _IOC(IOC_INOUT, ord(group_chr), num, length)


MAP_REP_FMT = "<iIII"
MAP_REP_SIZE = struct.calcsize(MAP_REP_FMT)
DRAWFSGIOC_MAP_SURFACE = _IOWR("D", 0x02, MAP_REP_SIZE)


def map_surface_ioctl(fd, surface_id: int):
    # The kernel accepts a small in/out buffer for the Step11 test flow.
    buf = bytearray(MAP_REP_SIZE)
    struct.pack_into("<iI", buf, 0, 0, surface_id)
    fcntl.ioctl(fd, DRAWFSGIOC_MAP_SURFACE, buf, True)
    return struct.unpack_from(MAP_REP_FMT, buf, 0)


def session_create_present_once(fd, cookie: int):
    # HELLO
    hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
    os.write(fd, make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)]))
    _ = os.read(fd, 4096)

    # DISPLAY_OPEN (display_id=1)
    open_payload = struct.pack("<I", 1)
    os.write(fd, make_frame(2, [make_msg(REQ_DISPLAY_OPEN, 2, open_payload)]))
    _ = os.read(fd, 4096)

    # SURFACE_CREATE 256x256 XRGB8888
    sc_req = struct.pack("<IIII", 256, 256, 1, 0)
    os.write(fd, make_frame(3, [make_msg(REQ_SURFACE_CREATE, 3, sc_req)]))
    msg_type, _mid, pl = read_one(fd)
    assert msg_type == RPL_SURFACE_CREATE
    st, sid, stride, total = decode_surface_create(pl)
    if st != 0:
        raise SystemExit(f"FAIL: surface create failed st={st}")

    # MAP_SURFACE and mmap
    st2, sid2, stride2, total2 = map_surface_ioctl(fd, sid)
    if st2 != 0:
        raise SystemExit(f"FAIL: map_surface ioctl failed st={st2}")
    if sid2 != sid or stride2 != stride or total2 != total:
        raise SystemExit("FAIL: map_surface rep mismatch")

    mm = mmap.mmap(fd, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
    try:
        mm[:64] = b"\xff\xff\xff\x00" * 16
        mm.flush()
        back = mm[:64]
        assert back == b"\xff\xff\xff\x00" * 16
    finally:
        mm.close()

    # SURFACE_PRESENT
    pres_req = struct.pack("<IIQ", sid, 0, cookie)
    os.write(fd, make_frame(4, [make_msg(REQ_SURFACE_PRESENT, 4, pres_req)]))

    # reply then event
    msg_type, _mid, pl = read_one(fd)
    assert msg_type == RPL_SURFACE_PRESENT
    st3, sid3, cookie3 = decode_surface_present_reply(pl)
    if st3 != 0 or sid3 != sid or cookie3 != cookie:
        raise SystemExit("FAIL: surface present reply mismatch")

    msg_type, _mid, pl = read_one(fd)
    assert msg_type == EVT_SURFACE_PRESENTED
    sid4, _flags4, cookie4 = decode_surface_presented_event(pl)
    if sid4 != sid or cookie4 != cookie:
        raise SystemExit("FAIL: surface presented event mismatch")

    return sid


def main():
    # Session 1
    fd = os.open(DEV, os.O_RDWR)
    try:
        old_sid = session_create_present_once(fd, cookie=0x1111111111111111)
    finally:
        os.close(fd)

    # Session 2
    fd2 = os.open(DEV, os.O_RDWR)
    try:
        # HELLO
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd2, make_frame(10, [make_msg(REQ_HELLO, 10, hello_payload)]))
        _ = os.read(fd2, 4096)

        # DISPLAY_OPEN
        open_payload = struct.pack("<I", 1)
        os.write(fd2, make_frame(11, [make_msg(REQ_DISPLAY_OPEN, 11, open_payload)]))
        _ = os.read(fd2, 4096)

        # Old surface id must not exist in the new session
        st, _sid, _stride, _total = map_surface_ioctl(fd2, old_sid)
        if st not in (errno.ENOENT, errno.EINVAL):
            raise SystemExit(f"FAIL: expected map(old_sid) to fail, got st={st}")

        # New surface id should start at 1 again
        sc_req = struct.pack("<IIII", 64, 64, 1, 0)
        os.write(fd2, make_frame(12, [make_msg(REQ_SURFACE_CREATE, 12, sc_req)]))
        msg_type, _mid, pl = read_one(fd2)
        assert msg_type == RPL_SURFACE_CREATE
        st2, sid2, _stride2, _total2 = decode_surface_create(pl)
        if st2 != 0:
            raise SystemExit(f"FAIL: surface create failed in new session st={st2}")
        if sid2 != 1:
            raise SystemExit(f"FAIL: expected new session surface_id=1, got {sid2}")

        print("OK: Step 15 session cleanup and reopen passed")
    finally:
        os.close(fd2)


if __name__ == "__main__":
    main()
