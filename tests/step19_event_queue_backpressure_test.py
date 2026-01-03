#!/usr/bin/env python3
"""Step 19: Event queue backpressure

Goal
  Confirm the kernel enforces a bounded per-session output queue (events and replies).
  When the queue is full, subsequent writes should fail with ENOSPC until userland drains
  the device by reading.

Notes
  - This test intentionally *does not read* for a while to let the kernel queue grow.
  - Once ENOSPC is observed, we start reading and then verify writes succeed again.

Environment
  - FreeBSD 15
  - Python 3
"""

import errno
from drawfs_test import (
    DrawSession, make_frame, make_msg, REQ_SURFACE_PRESENT,
    RPL_SURFACE_CREATE, drain_all
)


def main():
    with DrawSession() as s:
        # Setup: HELLO, DISPLAY_OPEN, SURFACE_CREATE
        s.hello()
        s.display_open()
        status, sid, stride, total = s.surface_create(256, 256)
        print(f"SURFACE_CREATE: ({status}, {sid}, {stride}, {total})")
        if status != 0:
            raise SystemExit("FAIL: surface create failed")

        # Drain any remaining setup replies
        s.drain_all(max_msgs=10, timeout_s=0.5)

        # Now intentionally *stop reading* and spam SURFACE_PRESENT to fill the kernel queue.
        cookie = 0x1234567890ABCDEF
        import struct
        present_payload = struct.pack("<IIQ", sid, 0, cookie)

        hit = False
        for i in range(1, 5000):
            frame = make_frame(100 + i, [make_msg(REQ_SURFACE_PRESENT, 100 + i, present_payload)])
            try:
                s.send(frame)
            except OSError as e:
                if e.errno == errno.ENOSPC:
                    print(f"OK: hit backpressure (ENOSPC) after {i} presents")
                    hit = True
                    break
                raise

        if not hit:
            raise SystemExit("FAIL: did not hit backpressure limit")

        # Drain frames to make space again.
        drained = s.drain_all(max_msgs=500, timeout_s=5.0)
        print(f"OK: drained {drained} frames")

        # Verify we can write again after draining.
        try:
            s.send(make_frame(9000, [make_msg(REQ_SURFACE_PRESENT, 9000, present_payload)]))
        except OSError as e:
            if e.errno == errno.ENOSPC:
                raise SystemExit("FAIL: still ENOSPC after draining")
            raise

        print("OK: Step 19 event queue backpressure passed")


if __name__ == "__main__":
    main()
