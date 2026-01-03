#!/usr/bin/env python3
"""Step 12: SURFACE_PRESENT end-to-end smoke test

Flow:
 1) HELLO
 2) DISPLAY_OPEN (display_id=1)
 3) SURFACE_CREATE (XRGB8888)
 4) DRAWFSGIOC_MAP_SURFACE ioctl -> returns stride + total bytes
 5) mmap() surface and write a simple pattern
 6) SURFACE_PRESENT(surface_id)
 7) Read reply + presented event
"""

import mmap
from drawfs_test import DrawSession


def main():
    with DrawSession() as s:
        # Setup
        s.hello()
        s.display_open()

        # SURFACE_CREATE (256x256, XRGB8888)
        w, h = 256, 256
        status, sid, stride, total = s.surface_create(w, h)
        print(f"SURFACE_CREATE: ({status}, {sid}, {stride}, {total})")
        if status != 0:
            raise SystemExit("FAIL: surface create failed")

        # MAP_SURFACE ioctl
        status, sid2, stride2, total2 = s.map_surface(sid)
        print(f"MAP_SURFACE ioctl: ({status}, {sid2}, {stride2}, {total2})")
        if status != 0:
            raise SystemExit("FAIL: map_surface ioctl failed")
        if sid2 != sid:
            raise SystemExit("FAIL: ioctl returned wrong surface_id")

        # mmap and draw a simple top-left checker pattern
        mm = mmap.mmap(s.fd, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            # paint 64x64 alternating white and black pixels
            for y in range(64):
                row = bytearray(stride2)
                for x in range(64):
                    is_white = ((x >> 3) ^ (y >> 3)) & 1
                    # XRGB8888: BB GG RR 00 in little-endian
                    if is_white:
                        row[x*4:x*4+4] = b"\xff\xff\xff\x00"
                    else:
                        row[x*4:x*4+4] = b"\x00\x00\x00\x00"
                mm[y*stride2:(y+1)*stride2] = row
            mm.flush()
        finally:
            mm.close()

        # SURFACE_PRESENT
        cookie = 0x1122334455667788
        status, rep_sid, rep_cookie = s.surface_present(sid, cookie)
        print(f"SURFACE_PRESENT reply: ({status}, {rep_sid}, {rep_cookie})")
        if status != 0:
            raise SystemExit(f"FAIL: surface present status={status}")
        if rep_sid != sid or rep_cookie != cookie:
            raise SystemExit("FAIL: SURFACE_PRESENT reply mismatch")

        # Read SURFACE_PRESENTED event
        ev_sid, ev_reserved, ev_cookie = s.read_presented_event()
        print(f"SURFACE_PRESENTED event: ({ev_sid}, {ev_reserved}, {ev_cookie})")
        if ev_sid != sid:
            raise SystemExit("FAIL: event surface_id mismatch")
        if ev_cookie != cookie:
            raise SystemExit("FAIL: event cookie mismatch")

        print("OK: present path completed")


if __name__ == "__main__":
    main()
