#!/usr/bin/env python3
"""Step 14: Multi surface round robin present test."""

import mmap
import struct
from drawfs_test import (
    DrawSession, read_msg, EVT_SURFACE_PRESENTED, RPL_SURFACE_PRESENT
)


def fill_pattern(mm, stride: int, w: int, h: int, rgba32: int):
    """Fill mmap buffer with a solid color pattern."""
    px = struct.pack("<I", rgba32)
    row = px * w
    for y in range(h):
        start = y * stride
        mm[start:start + 4*w] = row


def main():
    with DrawSession() as s:
        # Setup
        s.hello()
        s.display_list()
        s.display_open()

        # Create 3 surfaces 64x64 XRGB8888
        surfaces = []
        for i in range(3):
            status, sid, stride, total = s.surface_create(64, 64)
            if status != 0 or sid == 0:
                raise SystemExit(f"FAIL: surface create failed status={status} sid={sid}")
            surfaces.append((sid, stride, total, 64, 64))
        print("SURFACES:", [(surf[0], surf[1], surf[2]) for surf in surfaces])

        # For each surface, map and write a unique pattern
        patterns = [0x00FFFFFF, 0x0000FF00, 0x00FF0000]  # white, green, red (XRGB)
        for (sid, stride, total, w, h), rgba in zip(surfaces, patterns):
            st, _sid2, stride2, total2 = s.map_surface(sid)
            if st != 0:
                raise SystemExit(f"FAIL: MAP_SURFACE failed for sid={sid} status={st}")
            mm = mmap.mmap(s.fd, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
            try:
                fill_pattern(mm, stride2, w, h, rgba)
                mm.flush()
                # quick readback of first pixel
                first = struct.unpack_from("<I", mm, 0)[0]
                if first != rgba:
                    raise SystemExit(f"FAIL: readback mismatch sid={sid} got=0x{first:08x} want=0x{rgba:08x}")
            finally:
                mm.close()

        # Present round robin and verify reply and event ordering and cookie integrity
        for i in range(9):
            sid, stride, total, w, h = surfaces[i % len(surfaces)]
            cookie = 0xABC00000_00000000 | i

            status, sid_r, cookie_r = s.surface_present(sid, cookie)
            if status != 0 or sid_r != sid or cookie_r != cookie:
                raise SystemExit(f"FAIL: present reply mismatch st={status} sid={sid_r} cookie=0x{cookie_r:x}")

            mt, _mid, payload = read_msg(s.fd)
            if mt != EVT_SURFACE_PRESENTED:
                raise SystemExit(f"FAIL: expected SURFACE_PRESENTED event 0x{EVT_SURFACE_PRESENTED:x}, got 0x{mt:x}")
            sid_e, st_e, cookie_e = struct.unpack_from("<IIQ", payload, 0)
            if sid_e != sid or st_e != 0 or cookie_e != cookie:
                raise SystemExit(f"FAIL: presented event mismatch sid={sid_e} st={st_e} cookie=0x{cookie_e:x}")

        print("OK: Step 14 multi surface round robin present passed")


if __name__ == "__main__":
    main()
