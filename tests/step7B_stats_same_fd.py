#!/usr/bin/env python3
"""Step 7B: Activity + stats on same fd test."""

import os
import select
import struct
from drawfs_test import (
    DEV, make_frame, make_msg, get_stats,
    REQ_HELLO, REQ_DISPLAY_LIST
)


def print_stats(tag, st):
    print(f"== stats: {tag} ==")
    for k, v in st.items():
        print(f"{k:25} {v}")


def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        print("== Step 7B: activity + stats on same fd ==")

        st0 = get_stats(fd)
        print_stats("initial", st0)

        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        m1 = make_msg(REQ_HELLO, 201, hello_payload)
        m2 = make_msg(REQ_DISPLAY_LIST, 202, b"")
        frame = make_frame(20, [m1, m2])  # multi-message frame

        p = select.poll()
        p.register(fd, select.POLLIN | select.POLLRDNORM)

        os.write(fd, frame)

        ev = p.poll(1000)
        print("poll after write:", ev)
        if not ev:
            raise SystemExit("FAIL: poll did not report readable")

        r1 = os.read(fd, 4096)
        print(f"reply 1 bytes {len(r1)}")
        print(r1.hex())

        r2 = os.read(fd, 4096)
        print(f"reply 2 bytes {len(r2)}")
        print(r2.hex())

        st1 = get_stats(fd)
        print_stats("after traffic", st1)

        # RPL_HELLO: 16 (frame hdr) + 12 (msg hdr) + 16 (payload) = 44
        # RPL_DISPLAY_LIST: 16 (frame hdr) + 12 (msg hdr) + 28 (payload) = 56
        expected_out = 44 + 56
        if st1['bytes_out'] != expected_out:
            raise SystemExit(f"FAIL: bytes_out expected {expected_out}, got {st1['bytes_out']}")
        print("OK: step7B")
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
