#!/usr/bin/env python3
"""
test_surface.py - Surface lifecycle tests

Tests:
  - Surface creation (valid, invalid format, before display open)
  - Surface destruction (valid, double-destroy, invalid ID)
  - Surface mmap and read/write
  - Surface present and event delivery
  - Multi-surface round-robin presentation
"""

import errno
import mmap
import select
import struct
import time
from drawfs_test import (
    DrawSession, FMT_XRGB8888,
    RPL_SURFACE_CREATE, RPL_ERROR
)


def test_surface_create_valid():
    """Create a valid surface after display open."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        status, sid, stride, total = s.surface_create(256, 256)
        assert status == 0, f"SURFACE_CREATE failed with status {status}"
        assert sid >= 1, f"Invalid surface_id {sid}"
        assert stride >= 256 * 4, f"Stride too small: {stride}"
        assert total >= 256 * stride, f"Total too small: {total}"
        print(f"  Created surface: id={sid}, stride={stride}, total={total}")


def test_surface_create_before_display():
    """Surface creation before DISPLAY_OPEN should fail."""
    with DrawSession() as s:
        s.hello()
        # Skip display_open

        status, sid, stride, total = s.surface_create(256, 256)
        assert status != 0, "Expected SURFACE_CREATE to fail before display open"
        print(f"  Got expected error status: {status}")


def test_surface_create_invalid_format():
    """Surface creation with invalid format should fail."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        # Use invalid format (0xDEAD)
        status, sid, stride, total = s.surface_create(256, 256, fmt=0xDEAD)
        assert status != 0, "Expected SURFACE_CREATE to fail with invalid format"
        print(f"  Got expected error status: {status}")


def test_surface_destroy_valid():
    """Destroy a created surface."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        status, sid, stride, total = s.surface_create(128, 128)
        assert status == 0, f"SURFACE_CREATE failed: {status}"

        destroy_status = s.surface_destroy(sid)
        assert destroy_status == 0, f"SURFACE_DESTROY failed: {destroy_status}"
        print(f"  Destroyed surface {sid}")


def test_surface_destroy_double():
    """Double-destroy should fail."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        status, sid, stride, total = s.surface_create(128, 128)
        assert status == 0

        # First destroy
        st1 = s.surface_destroy(sid)
        assert st1 == 0

        # Second destroy should fail
        st2 = s.surface_destroy(sid)
        assert st2 != 0, "Expected double-destroy to fail"
        print(f"  Double-destroy correctly failed with status {st2}")


def test_surface_destroy_invalid_id():
    """Destroy with invalid surface_id should fail."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        # Try to destroy surface_id=0 (invalid)
        status = s.surface_destroy(0)
        assert status != 0, "Expected destroy(0) to fail"

        # Try to destroy non-existent surface
        status = s.surface_destroy(9999)
        assert status != 0, "Expected destroy(9999) to fail"
        print(f"  Invalid ID destroy correctly failed")


def test_surface_mmap():
    """Map surface and verify read/write."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        status, sid, stride, total = s.surface_create(64, 64)
        assert status == 0

        # MAP_SURFACE ioctl
        st, sid2, stride2, total2 = s.map_surface(sid)
        assert st == 0, f"MAP_SURFACE failed: {st}"
        assert sid2 == sid
        assert stride2 == stride
        assert total2 == total

        # mmap and write pattern
        mm = mmap.mmap(s.fd, total, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            pattern = b"\xff\x00\xff\x00" * 16  # 64 bytes
            mm[:64] = pattern
            mm.flush()

            # Read back
            readback = mm[:64]
            assert readback == pattern, "mmap read/write mismatch"
            print(f"  mmap read/write verified for surface {sid}")
        finally:
            mm.close()


def test_surface_present():
    """Present surface and receive event."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        status, sid, stride, total = s.surface_create(64, 64)
        assert status == 0

        st, _, _, _ = s.map_surface(sid)
        assert st == 0

        # Write something
        mm = mmap.mmap(s.fd, total, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            mm[:64] = b"\xff\xff\xff\x00" * 16
            mm.flush()
        finally:
            mm.close()

        # Present
        cookie = 0xCAFEBABE12345678
        pstatus, psid, pcookie = s.surface_present(sid, cookie)
        assert pstatus == 0, f"SURFACE_PRESENT failed: {pstatus}"
        assert psid == sid
        assert pcookie == cookie

        # Read event
        ev_sid, ev_reserved, ev_cookie = s.read_presented_event()
        assert ev_sid == sid, f"Event surface_id mismatch: {ev_sid} != {sid}"
        assert ev_reserved == 0, f"Event reserved field not zero: {ev_reserved}"
        assert ev_cookie == cookie, f"Event cookie mismatch: {ev_cookie} != {cookie}"
        print(f"  Present and event verified for surface {sid}")


def test_present_sequence():
    """Multiple presents maintain correct ordering and cookie integrity."""
    with DrawSession() as s:
        p = select.poll()
        p.register(s.fd, select.POLLIN | getattr(select, "POLLRDNORM", 0))

        s.hello()
        s.display_open()

        status, sid, stride, total = s.surface_create(64, 64)
        assert status == 0

        st, _, _, _ = s.map_surface(sid)
        assert st == 0

        # Do 5 presents with distinct cookies
        for i in range(5):
            cookie = (int(time.time_ns()) ^ (i * 0x9e3779b97f4a7c15)) & 0xFFFFFFFFFFFFFFFF

            pstatus, psid, pcookie = s.surface_present(sid, cookie)
            assert pstatus == 0
            assert psid == sid
            assert pcookie == cookie

            # Wait for event
            ev = p.poll(1000)
            assert ev, f"Timeout waiting for event {i}"

            ev_sid, ev_reserved, ev_cookie = s.read_presented_event()
            assert ev_sid == sid
            assert ev_reserved == 0
            assert ev_cookie == cookie

        print(f"  5 sequential presents verified")


def test_multi_surface_round_robin():
    """Multiple surfaces with round-robin presentation."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        # Create 3 surfaces
        surfaces = []
        for i in range(3):
            status, sid, stride, total = s.surface_create(64, 64)
            assert status == 0
            surfaces.append((sid, stride, total))

        # Map and paint each with different color
        colors = [b"\xff\x00\x00\x00", b"\x00\xff\x00\x00", b"\x00\x00\xff\x00"]
        for i, (sid, stride, total) in enumerate(surfaces):
            st, _, _, _ = s.map_surface(sid)
            assert st == 0

            mm = mmap.mmap(s.fd, total, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
            try:
                mm[:64] = colors[i] * 16
                mm.flush()
            finally:
                mm.close()

        # Present each surface 3 times in round-robin
        for round_num in range(3):
            for i, (sid, _, _) in enumerate(surfaces):
                cookie = (round_num << 16) | (i << 8) | 0xAA

                pstatus, psid, pcookie = s.surface_present(sid, cookie)
                assert pstatus == 0
                assert psid == sid

                ev_sid, ev_reserved, ev_cookie = s.read_presented_event()
                assert ev_sid == sid
                assert ev_cookie == cookie

        print(f"  3 surfaces x 3 rounds verified")


def main():
    tests = [
        ("Surface create valid", test_surface_create_valid),
        ("Surface create before display", test_surface_create_before_display),
        ("Surface create invalid format", test_surface_create_invalid_format),
        ("Surface destroy valid", test_surface_destroy_valid),
        ("Surface destroy double", test_surface_destroy_double),
        ("Surface destroy invalid ID", test_surface_destroy_invalid_id),
        ("Surface mmap", test_surface_mmap),
        ("Surface present", test_surface_present),
        ("Present sequence", test_present_sequence),
        ("Multi-surface round-robin", test_multi_surface_round_robin),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            print(f"[TEST] {name}")
            test_fn()
            print(f"[PASS] {name}\n")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {name}: {e}\n")
            failed += 1

    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
