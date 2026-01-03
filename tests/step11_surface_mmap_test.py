#!/usr/bin/env python3
"""Step 11: Surface mmap test."""

import mmap
from drawfs_test import DrawSession


def main():
    with DrawSession() as s:
        # Setup
        s.hello()
        s.display_open()

        # SURFACE_CREATE 256x256
        status, sid, stride, total = s.surface_create(256, 256)
        print(f"SURFACE_CREATE: ({status}, {sid}, {stride}, {total})")
        if status != 0:
            raise SystemExit("FAIL: surface create failed")

        # MAP_SURFACE ioctl
        st, sid2, stride2, total2 = s.map_surface(sid)
        print(f"MAP_SURFACE ioctl rep: ({st}, {sid2}, {stride2}, {total2})")
        if st != 0:
            raise SystemExit("FAIL: map_surface ioctl failed")

        # mmap and write a simple pattern into first row
        mm = mmap.mmap(s.fd, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            # write 16 pixels of white in XRGB8888
            mm[:64] = b"\xff\xff\xff\x00" * 16
            mm.flush()
            # read back
            back = mm[:64]
            assert back == b"\xff\xff\xff\x00" * 16
            print("MMAP write/readback OK")
        finally:
            mm.close()


if __name__ == "__main__":
    main()
