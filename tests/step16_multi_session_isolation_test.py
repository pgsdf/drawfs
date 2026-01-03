#!/usr/bin/env python3
"""Step 16: Multi-session isolation test.

Verify that two independent sessions (two open fds) have completely
separate state - surfaces created in one session are not visible in the other.
"""

import mmap
from drawfs_test import DrawSession


def main():
    # Open two independent sessions
    with DrawSession() as s1, DrawSession() as s2:
        # Setup both sessions
        s1.hello()
        s1.display_open()

        s2.hello()
        s2.display_open()

        # Create surfaces in each session
        status1, sid1, stride1, total1 = s1.surface_create(256, 256)
        if status1 != 0:
            raise SystemExit(f"FAIL: session 1 surface create failed: {status1}")

        status2, sid2, stride2, total2 = s2.surface_create(256, 256)
        if status2 != 0:
            raise SystemExit(f"FAIL: session 2 surface create failed: {status2}")

        # Map and write to surfaces
        st1 = s1.map_surface(sid1)
        st2 = s2.map_surface(sid2)
        if st1[0] != 0 or st2[0] != 0:
            raise SystemExit("FAIL: map_surface failed")

        mm1 = mmap.mmap(s1.fd, st1[3], mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        mm2 = mmap.mmap(s2.fd, st2[3], mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            # Write different patterns to each surface
            mm1[:64] = b"\xff\xff\xff\x00" * 16  # white
            mm2[:64] = b"\x00\xff\x00\x00" * 16  # green
            mm1.flush()
            mm2.flush()
        finally:
            mm1.close()
            mm2.close()

        # Present from each session
        cookie1 = 0x1111111111111111
        cookie2 = 0x2222222222222222

        status, rep_sid, rep_cookie = s1.surface_present(sid1, cookie1)
        if status != 0:
            raise SystemExit(f"FAIL: session 1 present failed: {status}")

        status, rep_sid, rep_cookie = s2.surface_present(sid2, cookie2)
        if status != 0:
            raise SystemExit(f"FAIL: session 2 present failed: {status}")

        # Read presented events
        psid1, _, pcookie1 = s1.read_presented_event()
        psid2, _, pcookie2 = s2.read_presented_event()

        if psid1 != sid1 or pcookie1 != cookie1:
            raise SystemExit("FAIL: session 1 event mismatch")
        if psid2 != sid2 or pcookie2 != cookie2:
            raise SystemExit("FAIL: session 2 event mismatch")

        print("OK: Step 16 multi session isolation passed")


if __name__ == "__main__":
    main()
