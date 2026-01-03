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
import mmap
from drawfs_test import DrawSession


def session_create_present_once(s, cookie: int):
    """Create surface, write pattern, present, and return surface_id."""
    s.hello()
    s.display_open()

    # SURFACE_CREATE 256x256 XRGB8888
    status, sid, stride, total = s.surface_create(256, 256)
    if status != 0:
        raise SystemExit(f"FAIL: surface create failed st={status}")

    # MAP_SURFACE and mmap
    st2, sid2, stride2, total2 = s.map_surface(sid)
    if st2 != 0:
        raise SystemExit(f"FAIL: map_surface ioctl failed st={st2}")
    if sid2 != sid or stride2 != stride or total2 != total:
        raise SystemExit("FAIL: map_surface rep mismatch")

    mm = mmap.mmap(s.fd, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
    try:
        mm[:64] = b"\xff\xff\xff\x00" * 16
        mm.flush()
        back = mm[:64]
        assert back == b"\xff\xff\xff\x00" * 16
    finally:
        mm.close()

    # SURFACE_PRESENT
    status, sid3, cookie3 = s.surface_present(sid, cookie)
    if status != 0 or sid3 != sid or cookie3 != cookie:
        raise SystemExit("FAIL: surface present reply mismatch")

    # Read event
    sid4, _flags4, cookie4 = s.read_presented_event()
    if sid4 != sid or cookie4 != cookie:
        raise SystemExit("FAIL: surface presented event mismatch")

    return sid


def main():
    # Session 1
    with DrawSession() as s1:
        old_sid = session_create_present_once(s1, cookie=0x1111111111111111)

    # Session 2 (after closing session 1)
    with DrawSession() as s2:
        s2.hello()
        s2.display_open()

        # Old surface id must not exist in the new session
        st, _sid, _stride, _total = s2.map_surface(old_sid)
        if st not in (errno.ENOENT, errno.EINVAL):
            raise SystemExit(f"FAIL: expected map(old_sid) to fail, got st={st}")

        # New surface id should start at 1 again
        status, sid2, _stride2, _total2 = s2.surface_create(64, 64)
        if status != 0:
            raise SystemExit(f"FAIL: surface create failed in new session st={status}")
        if sid2 != 1:
            raise SystemExit(f"FAIL: expected new session surface_id=1, got {sid2}")

        print("OK: Step 15 session cleanup and reopen passed")


if __name__ == "__main__":
    main()
