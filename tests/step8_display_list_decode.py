#!/usr/bin/env python3
"""Step 8: Display list decode test."""

import os
import struct
from drawfs_test import (
    DEV, make_frame, make_msg, parse_first_msg,
    REQ_HELLO, REQ_DISPLAY_LIST
)


def decode_display_list(payload: bytes):
    (count,) = struct.unpack_from("<I", payload, 0)
    print("display count:", count)
    desc_fmt = "<IIIII"
    desc_sz = struct.calcsize(desc_fmt)
    for i in range(count):
        base = 4 + i * desc_sz
        display_id, w, h, refresh_mhz, flags = struct.unpack_from(desc_fmt, payload, base)
        print(f"  display[{i}] id={display_id} {w}x{h} refresh_mhz={refresh_mhz} flags=0x{flags:x}")


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
        msg_type, msg_id, payload = parse_first_msg(r)
        print(f"DISPLAY_LIST reply msg_type=0x{msg_type:x} msg_id={msg_id} payload_bytes={len(payload)}")
        decode_display_list(payload)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
