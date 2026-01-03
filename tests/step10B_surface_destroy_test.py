#!/usr/bin/env python3
"""Step 10B: Surface destroy test."""

import errno
from drawfs_test import DrawSession


def main():
    with DrawSession() as s:
        s.hello()
        s.display_open()

        # Create a surface
        status, sid, stride, total = s.surface_create(320, 240)
        print(f"SURFACE_CREATE: ({status}, {sid}, {stride}, {total})")
        if status != 0 or sid == 0:
            raise SystemExit("FAIL: expected a valid surface_id")

        print("== Destroy existing surface (expect 0) ==")
        status = s.surface_destroy(sid)
        print(f"SURFACE_DESTROY: ({status}, {sid})")
        if status != 0:
            raise SystemExit(f"FAIL: expected status 0, got {status}")

        print("== Destroy same surface again (expect errno.ENOENT) ==")
        status = s.surface_destroy(sid)
        print(f"SURFACE_DESTROY: ({status}, {sid})")
        print(f"errno.ENOENT = {errno.ENOENT}")

        print("== Destroy surface_id=0 (expect errno.EINVAL) ==")
        status = s.surface_destroy(0)
        print(f"SURFACE_DESTROY: ({status}, 0)")
        print(f"errno.EINVAL = {errno.EINVAL}")


if __name__ == "__main__":
    main()
