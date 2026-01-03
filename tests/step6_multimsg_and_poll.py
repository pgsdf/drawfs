#!/usr/bin/env python3
"""Step 6: Multi-message in one frame + poll readiness test."""

import os
import select
import struct
from drawfs_test import (
    DEV, make_frame, make_msg, REQ_HELLO, REQ_DISPLAY_LIST
)


def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        print("== multi-message in one frame + poll readiness ==")
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)

        m1 = make_msg(REQ_HELLO, 101, hello_payload)
        m2 = make_msg(REQ_DISPLAY_LIST, 102, b"")
        frame = make_frame(10, [m1, m2])

        p = select.poll()
        p.register(fd, select.POLLIN | select.POLLRDNORM)

        before = p.poll(0)
        print("poll before write:", before)

        os.write(fd, frame)

        after = p.poll(1000)
        print("poll after write:", after)
        if not after:
            raise SystemExit("FAIL: poll did not report readable after write")

        r1 = os.read(fd, 4096)
        print(f"reply 1 bytes {len(r1)}")
        print(r1.hex())

        r2 = os.read(fd, 4096)
        print(f"reply 2 bytes {len(r2)}")
        print(r2.hex())

        print("PASS")
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
