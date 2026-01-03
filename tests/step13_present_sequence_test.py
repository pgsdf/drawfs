#!/usr/bin/env python3
"""Step 13: present sequencing and event ordering smoke test.

Validates:
  - SURFACE_PRESENT reply status is 0 for valid surface/display
  - A SURFACE_PRESENTED event follows each successful present
  - The cookie in the reply matches the cookie in the event
  - Multiple presents are processed in order (best-effort check)

Run:
  sudo python3 tests/step13_present_sequence_test.py
"""

import select
import time
from drawfs_test import DrawSession


def main():
    with DrawSession() as s:
        p = select.poll()
        p.register(s.fd, select.POLLIN | getattr(select, "POLLRDNORM", 0))

        s.hello()
        s.display_list()
        s.display_open()

        status, sid, stride, total = s.surface_create(256, 256)
        if status != 0:
            raise SystemExit(f"FAIL: SURFACE_CREATE status={status}")

        st, sid2, stride2, total2 = s.map_surface(sid)
        if st != 0:
            raise SystemExit(f"FAIL: MAP_SURFACE status={st}")
        if total2 != total:
            raise SystemExit("FAIL: MAP_SURFACE total mismatch")

        # do 3 presents with distinct cookies and ensure reply+event match
        for i in range(3):
            cookie = (int(time.time_ns()) ^ (i * 0x9e3779b97f4a7c15)) & 0xFFFFFFFFFFFFFFFF
            status, rsid, rcookie = s.surface_present(sid, cookie)
            if status != 0:
                raise SystemExit(f"FAIL: SURFACE_PRESENT status={status}")
            if rsid != sid or rcookie != cookie:
                raise SystemExit("FAIL: SURFACE_PRESENT reply mismatch")
            # poll should show readable for the event
            ev = p.poll(1000)
            if not ev:
                raise SystemExit("FAIL: poll did not show readable for event")
            esid, estatus, ecookie = s.read_presented_event()
            if esid != sid or estatus != 0 or ecookie != cookie:
                raise SystemExit("FAIL: SURFACE_PRESENTED event mismatch")

        print("OK: Step 13 present sequencing passed")


if __name__ == "__main__":
    main()
