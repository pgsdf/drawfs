#!/usr/bin/env python3
"""Step 9: Display open test."""

import os
import struct
from drawfs_test import (
    DEV, make_frame, make_msg, parse_first_msg,
    REQ_HELLO, REQ_DISPLAY_LIST, REQ_DISPLAY_OPEN
)


def decode_display_list(payload: bytes):
    (count,) = struct.unpack_from("<I", payload, 0)
    desc_fmt = "<IIIII"
    desc_sz = struct.calcsize(desc_fmt)
    displays = []
    for i in range(count):
        base = 4 + i * desc_sz
        display_id, w, h, refresh_mhz, flags = struct.unpack_from(desc_fmt, payload, base)
        displays.append((display_id, w, h, refresh_mhz, flags))
    return displays


def decode_display_open(payload: bytes):
    return struct.unpack_from("<iII", payload, 0)


def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        # HELLO
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)]))
        _ = os.read(fd, 4096)

        # DISPLAY_LIST
        os.write(fd, make_frame(2, [make_msg(REQ_DISPLAY_LIST, 2, b"")]))
        r = os.read(fd, 4096)
        _t, _id, payload = parse_first_msg(r)
        displays = decode_display_list(payload)
        print("DISPLAY_LIST:", displays)

        # DISPLAY_OPEN (valid)
        open_payload = struct.pack("<I", 1)
        os.write(fd, make_frame(3, [make_msg(REQ_DISPLAY_OPEN, 3, open_payload)]))
        r2 = os.read(fd, 4096)
        _t2, _id2, payload2 = parse_first_msg(r2)
        status, handle, active_id = decode_display_open(payload2)
        print(f"DISPLAY_OPEN: status={status} handle={handle} active_id={active_id}")

        # DISPLAY_OPEN (invalid id)
        bad_payload = struct.pack("<I", 99)
        os.write(fd, make_frame(4, [make_msg(REQ_DISPLAY_OPEN, 4, bad_payload)]))
        r3 = os.read(fd, 4096)
        _t3, _id3, payload3 = parse_first_msg(r3)
        status2, handle2, active_id2 = decode_display_open(payload3)
        print(f"DISPLAY_OPEN(bad): status={status2} handle={handle2} active_id={active_id2}")
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
