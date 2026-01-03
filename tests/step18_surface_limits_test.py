#!/usr/bin/env python3
"""Step 18 surface limits test.

This verifies two DoS resistance limits:
1) Oversized surface creation returns errno.EFBIG.
2) Too many surfaces in a single session returns errno.ENOSPC.

The test uses the message framing protocol and does not require mmap.
"""

import errno
import os
import struct

DEV = "/dev/draw"

DRAWFS_MAGIC = 0x31575244
DRAWFS_VERSION = 0x0100

REQ_HELLO = 0x0001
REQ_DISPLAY_LIST = 0x0010
REQ_DISPLAY_OPEN = 0x0011
REQ_SURFACE_CREATE = 0x0020

FMT_XRGB8888 = 1

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


def read_reply(fd):
    buf = os.read(fd, 4096)
    if len(buf) < struct.calcsize(fh_fmt) + struct.calcsize(mh_fmt):
        raise RuntimeError(f"short read: {len(buf)}")
    off = struct.calcsize(fh_fmt)
    msg_type, msg_flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off + payload_len]
    return msg_type, msg_id, payload


def hello(fd, frame_id: int, msg_id: int):
    # client_id=1, flags=0, reserved=0, max_reply_bytes=65536
    payload = struct.pack("<HHII", 1, 0, 0, 65536)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_HELLO, msg_id, payload)]))
    os.read(fd, 4096)


def display_list(fd, frame_id: int, msg_id: int):
    os.write(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_LIST, msg_id, b"")]))
    _t, _mid, _pl = read_reply(fd)


def display_open(fd, frame_id: int, msg_id: int, display_id: int = 1):
    payload = struct.pack("<I", display_id)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_OPEN, msg_id, payload)]))
    os.read(fd, 4096)


def surface_create(fd, frame_id: int, msg_id: int, width: int, height: int):
    payload = struct.pack("<IIII", width, height, FMT_XRGB8888, 0)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_CREATE, msg_id, payload)]))
    _t, _mid, pl = read_reply(fd)
    st, sid, stride, total = struct.unpack_from("<iIII", pl, 0)
    return st, sid, stride, total


def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        hello(fd, frame_id=1, msg_id=1)
        display_list(fd, frame_id=2, msg_id=2)
        display_open(fd, frame_id=3, msg_id=3, display_id=1)

        # 1) Oversized surface should be rejected.
        # 4096x4097x4 = 67,125,248 bytes, which is larger than 64 MiB.
        st, _sid, _stride, _total = surface_create(fd, 4, 4, 4096, 4097)
        if st != errno.EFBIG:
            raise SystemExit(f"FAIL: expected EFBIG for oversized surface, got {st}")

        # 2) Too many surfaces should be rejected.
        created = []
        frame_id = 10
        msg_id = 10
        while True:
            st, sid, _stride, _total = surface_create(fd, frame_id, msg_id, 64, 64)
            frame_id += 1
            msg_id += 1
            if st == 0:
                created.append(sid)
                continue
            if st == errno.ENOSPC:
                break
            raise SystemExit(f"FAIL: expected ENOSPC once limit hit, got {st}")

        print(f"OK: surface limit hit after {len(created)} surfaces")
        print("OK: Step 18 surface limits passed")

    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
