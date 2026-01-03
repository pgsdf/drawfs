#!/usr/bin/env python3
"""Step 10A: Surface create test."""

import errno
from drawfs_test import DrawSession


def main():
    with DrawSession() as s:
        s.hello()

        print("== Surface create before display open (expect errno.EINVAL) ==")
        status, _sid, _stride, _total = s.surface_create(640, 480)
        print(f"SURFACE_CREATE: ({status}, surface_id=?, stride=?, total=?)")
        if status != errno.EINVAL:
            print(f"NOTE: expected EINVAL ({errno.EINVAL}), got {status}")

        print("== Display open then surface create (expect 0, surface_id>0) ==")
        s.display_open()

        status, sid, stride, total = s.surface_create(640, 480)
        print(f"SURFACE_CREATE: ({status}, {sid}, {stride}, {total})")
        if status != 0 or sid == 0:
            raise SystemExit("FAIL: expected a valid surface_id")

        print("== Unsupported format (expect errno.EPROTONOSUPPORT) ==")
        status, _sid, _stride, _total = s.surface_create(64, 64, fmt=999)
        print(f"SURFACE_CREATE: ({status}, ?, ?, ?)")
        print(f"errno.EPROTONOSUPPORT = {errno.EPROTONOSUPPORT}")


if __name__ == "__main__":
    main()
