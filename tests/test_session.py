#!/usr/bin/env python3
"""
test_session.py - Session isolation tests

Tests:
  - Session cleanup on close (surfaces freed, IDs reset)
  - Multi-session isolation (separate surface namespaces)
  - Interleaved operations across sessions
  - Session survives peer close
"""

import errno
import mmap
import os
import select
import struct
from drawfs_test import (
    DrawSession, DEV, make_frame, make_msg, parse_first_msg, map_surface,
    REQ_HELLO, REQ_DISPLAY_OPEN, REQ_SURFACE_CREATE, REQ_SURFACE_PRESENT,
    RPL_DISPLAY_OPEN, RPL_SURFACE_CREATE, RPL_SURFACE_PRESENT,
    EVT_SURFACE_PRESENTED, FMT_XRGB8888
)


def test_session_cleanup():
    """Closing session frees surfaces and resets IDs."""
    # Session 1: create surface, present, close
    with DrawSession() as s1:
        s1.hello()
        s1.display_open()

        status, sid1, stride, total = s1.surface_create(64, 64)
        assert status == 0
        assert sid1 == 1, f"First surface should be ID 1, got {sid1}"

        st, _, _, _ = s1.map_surface(sid1)
        assert st == 0

        mm = mmap.mmap(s1.fd, total, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            mm[:64] = b"\xff\xff\xff\x00" * 16
            mm.flush()
        finally:
            mm.close()

        pstatus, _, _ = s1.surface_present(sid1, 0x1111111111111111)
        assert pstatus == 0

        ev_sid, _, _ = s1.read_presented_event()
        assert ev_sid == sid1

        old_sid = sid1
    # Session 1 now closed

    # Session 2: old surface ID should not exist, new surface gets ID 1
    with DrawSession() as s2:
        s2.hello()
        s2.display_open()

        # Old surface should not be mappable
        st, _, _, _ = s2.map_surface(old_sid)
        assert st != 0, f"Old surface {old_sid} should not exist in new session"

        # New surface should get ID 1 again
        status, sid2, _, _ = s2.surface_create(64, 64)
        assert status == 0
        assert sid2 == 1, f"New session should start at ID 1, got {sid2}"

    print(f"  Session cleanup verified: old_sid={old_sid} freed, new session starts at 1")


def test_multi_session_isolation():
    """Two concurrent sessions have independent surface namespaces."""
    with DrawSession() as s1, DrawSession() as s2:
        # Init both sessions
        s1.hello()
        s1.display_open()
        s2.hello()
        s2.display_open()

        # Both should get surface ID 1
        st1, sid1, stride1, total1 = s1.surface_create(64, 64)
        st2, sid2, stride2, total2 = s2.surface_create(64, 64)

        assert st1 == 0 and st2 == 0
        assert sid1 == 1, f"Session 1 first surface should be 1, got {sid1}"
        assert sid2 == 1, f"Session 2 first surface should be 1, got {sid2}"

        # Map and paint different colors
        s1.map_surface(sid1)
        s2.map_surface(sid2)

        mm1 = mmap.mmap(s1.fd, total1, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        mm2 = mmap.mmap(s2.fd, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            mm1[:64] = b"\xff\x00\x00\x00" * 16  # Red
            mm2[:64] = b"\x00\xff\x00\x00" * 16  # Green
            mm1.flush()
            mm2.flush()

            # Verify isolation: each session reads its own color
            assert mm1[:4] == b"\xff\x00\x00\x00"
            assert mm2[:4] == b"\x00\xff\x00\x00"
        finally:
            mm1.close()
            mm2.close()

        # Present from both - events should be isolated
        ps1, _, _ = s1.surface_present(sid1, 0xAAAAAAAAAAAAAAAA)
        ps2, _, _ = s2.surface_present(sid2, 0xBBBBBBBBBBBBBBBB)
        assert ps1 == 0 and ps2 == 0

        ev1_sid, _, ev1_cookie = s1.read_presented_event()
        ev2_sid, _, ev2_cookie = s2.read_presented_event()

        assert ev1_cookie == 0xAAAAAAAAAAAAAAAA
        assert ev2_cookie == 0xBBBBBBBBBBBBBBBB

    print(f"  Multi-session isolation verified")


def test_interleaved_presents():
    """Interleaved presents across sessions maintain correct event routing."""
    fd1 = os.open(DEV, os.O_RDWR)
    fd2 = os.open(DEV, os.O_RDWR)

    def read_one(fd):
        buf = os.read(fd, 4096)
        return parse_first_msg(buf)

    def hello(fd, frame_id, msg_id):
        payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(frame_id, [make_msg(REQ_HELLO, msg_id, payload)]))
        os.read(fd, 4096)

    def display_open(fd, frame_id, msg_id):
        payload = struct.pack("<I", 1)
        os.write(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_OPEN, msg_id, payload)]))
        msg_type, _, payload = read_one(fd)
        assert msg_type == RPL_DISPLAY_OPEN

    def surface_create(fd, frame_id, msg_id, w, h):
        payload = struct.pack("<IIII", w, h, FMT_XRGB8888, 0)
        os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_CREATE, msg_id, payload)]))
        msg_type, _, payload = read_one(fd)
        assert msg_type == RPL_SURFACE_CREATE
        status, sid, stride, total = struct.unpack_from("<iIII", payload, 0)
        return sid, stride, total

    def present(fd, frame_id, msg_id, sid, cookie):
        payload = struct.pack("<IIQ", sid, 0, cookie)
        os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_PRESENT, msg_id, payload)]))
        msg_type, _, payload = read_one(fd)
        assert msg_type == RPL_SURFACE_PRESENT

    def wait_event(fd, timeout_ms=1000):
        p = select.poll()
        p.register(fd, select.POLLIN | select.POLLRDNORM)
        ev = p.poll(timeout_ms)
        assert ev, "Timeout waiting for event"
        msg_type, _, payload = read_one(fd)
        assert msg_type == EVT_SURFACE_PRESENTED
        sid, reserved, cookie = struct.unpack_from("<IIQ", payload, 0)
        return sid, reserved, cookie

    try:
        # Init both sessions
        hello(fd1, 1, 1)
        display_open(fd1, 2, 2)
        hello(fd2, 10, 10)
        display_open(fd2, 11, 11)

        # Create surfaces
        sid1, stride1, total1 = surface_create(fd1, 3, 3, 64, 64)
        sid2, stride2, total2 = surface_create(fd2, 12, 12, 64, 64)

        # Map and paint
        st, _, _, _ = map_surface(fd1, sid1)
        assert st == 0
        st, _, _, _ = map_surface(fd2, sid2)
        assert st == 0

        mm1 = mmap.mmap(fd1, total1, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        mm2 = mmap.mmap(fd2, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            mm1[:64] = b"\xff\xff\xff\x00" * 16
            mm2[:64] = b"\x00\xff\x00\x00" * 16
            mm1.flush()
            mm2.flush()

            # Interleaved presents
            cookie1a = 0x1111111111111111
            cookie2a = 0x2222222222222222
            present(fd1, 4, 4, sid1, cookie1a)
            present(fd2, 13, 13, sid2, cookie2a)

            # Each session should get its own event
            ev1_sid, _, ev1_cookie = wait_event(fd1)
            ev2_sid, _, ev2_cookie = wait_event(fd2)

            assert ev1_sid == sid1 and ev1_cookie == cookie1a
            assert ev2_sid == sid2 and ev2_cookie == cookie2a

            # Reverse order
            cookie1b = 0xAAAAAAAAAAAAAAAA
            cookie2b = 0xBBBBBBBBBBBBBBBB
            present(fd2, 14, 14, sid2, cookie2b)
            present(fd1, 5, 5, sid1, cookie1b)

            ev2_sid, _, ev2_cookie = wait_event(fd2)
            ev1_sid, _, ev1_cookie = wait_event(fd1)

            assert ev2_sid == sid2 and ev2_cookie == cookie2b
            assert ev1_sid == sid1 and ev1_cookie == cookie1b

        finally:
            mm1.close()
            mm2.close()

    finally:
        os.close(fd1)
        os.close(fd2)

    print(f"  Interleaved presents verified")


def test_session_survives_peer_close():
    """One session continues functioning after another closes."""
    fd1 = os.open(DEV, os.O_RDWR)
    fd2 = os.open(DEV, os.O_RDWR)

    def read_one(fd):
        buf = os.read(fd, 4096)
        return parse_first_msg(buf)

    def hello(fd, frame_id, msg_id):
        payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(frame_id, [make_msg(REQ_HELLO, msg_id, payload)]))
        os.read(fd, 4096)

    def display_open(fd, frame_id, msg_id):
        payload = struct.pack("<I", 1)
        os.write(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_OPEN, msg_id, payload)]))
        msg_type, _, _ = read_one(fd)
        assert msg_type == RPL_DISPLAY_OPEN

    def surface_create(fd, frame_id, msg_id, w, h):
        payload = struct.pack("<IIII", w, h, FMT_XRGB8888, 0)
        os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_CREATE, msg_id, payload)]))
        msg_type, _, payload = read_one(fd)
        assert msg_type == RPL_SURFACE_CREATE
        status, sid, stride, total = struct.unpack_from("<iIII", payload, 0)
        return sid, stride, total

    def present(fd, frame_id, msg_id, sid, cookie):
        payload = struct.pack("<IIQ", sid, 0, cookie)
        os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_PRESENT, msg_id, payload)]))
        msg_type, _, payload = read_one(fd)
        assert msg_type == RPL_SURFACE_PRESENT

    def wait_event(fd, timeout_ms=1000):
        p = select.poll()
        p.register(fd, select.POLLIN | select.POLLRDNORM)
        ev = p.poll(timeout_ms)
        assert ev, "Timeout waiting for event"
        msg_type, _, payload = read_one(fd)
        assert msg_type == EVT_SURFACE_PRESENTED
        sid, reserved, cookie = struct.unpack_from("<IIQ", payload, 0)
        return sid, reserved, cookie

    try:
        # Init both sessions
        hello(fd1, 1, 1)
        display_open(fd1, 2, 2)
        hello(fd2, 10, 10)
        display_open(fd2, 11, 11)

        # Create surface on session 2
        sid2, stride2, total2 = surface_create(fd2, 12, 12, 64, 64)
        st, _, _, _ = map_surface(fd2, sid2)
        assert st == 0

        mm2 = mmap.mmap(fd2, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            mm2[:64] = b"\x00\xff\x00\x00" * 16
            mm2.flush()

            # Close session 1
            os.close(fd1)
            fd1 = -1

            # Session 2 should still work
            present(fd2, 13, 13, sid2, 0xCCCCCCCCCCCCCCCC)
            ev_sid, _, ev_cookie = wait_event(fd2)
            assert ev_sid == sid2
            assert ev_cookie == 0xCCCCCCCCCCCCCCCC

        finally:
            mm2.close()

    finally:
        if fd1 != -1:
            os.close(fd1)
        os.close(fd2)

    print(f"  Session survives peer close verified")


def main():
    tests = [
        ("Session cleanup", test_session_cleanup),
        ("Multi-session isolation", test_multi_session_isolation),
        ("Interleaved presents", test_interleaved_presents),
        ("Session survives peer close", test_session_survives_peer_close),
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
