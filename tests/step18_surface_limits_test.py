#!/usr/bin/env python3
"""Step 18 surface limits test.

This verifies two DoS resistance limits:
1) Oversized surface creation returns errno.EFBIG.
2) Too many surfaces in a single session returns errno.ENOSPC.

The test uses the message framing protocol and does not require mmap.
"""

import errno
from drawfs_test import DrawSession


def main():
    with DrawSession() as s:
        s.hello()
        s.display_list()
        s.display_open()

        # 1) Oversized surface should be rejected.
        # 4096x4097x4 = 67,125,248 bytes, which is larger than 64 MiB.
        status, _sid, _stride, _total = s.surface_create(4096, 4097)
        if status != errno.EFBIG:
            raise SystemExit(f"FAIL: expected EFBIG for oversized surface, got {status}")
        print("OK: oversized surface rejected with EFBIG")

        # 2) Too many surfaces should be rejected.
        created = []
        while True:
            status, sid, _stride, _total = s.surface_create(64, 64)
            if status == 0:
                created.append(sid)
                continue
            if status == errno.ENOSPC:
                break
            raise SystemExit(f"FAIL: expected ENOSPC once limit hit, got {status}")

        print(f"OK: surface limit hit after {len(created)} surfaces")
        print("OK: Step 18 surface limits passed")


if __name__ == "__main__":
    main()
