#!/usr/bin/env python3
"""
test_limits.py - Limits, error handling, and backpressure tests

Tests:
  - Oversized surface rejection (EFBIG)
  - Maximum surface count (ENOSPC)
  - Event queue backpressure
  - Stats tracking for surfaces
"""

import errno
import os
import select
import struct
from drawfs_test import (
    DrawSession, DEV, make_frame, make_msg, parse_first_msg,
    REQ_HELLO, REQ_SURFACE_CREATE, REQ_SURFACE_PRESENT,
    RPL_SURFACE_CREATE, RPL_SURFACE_PRESENT, EVT_SURFACE_PRESENTED,
    FMT_XRGB8888
)


# Limits (from kernel)
MAX_SURFACE_SIZE = 64 * 1024 * 1024  # 64 MB
MAX_SURFACES = 64


def test_oversized_surface():
    """Oversized surface creation should fail with EFBIG."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        # Try to create a surface larger than 64 MB
        # 4096x4096 * 4 bytes = 64 MB (exactly at limit)
        # 4097x4096 * 4 bytes > 64 MB (over limit)
        w, h = 4097, 4096

        status, sid, stride, total = s.surface_create(w, h)
        assert status == errno.EFBIG, f"Expected EFBIG ({errno.EFBIG}), got {status}"
        print(f"  Oversized surface correctly rejected with EFBIG")


def test_max_surfaces():
    """Creating more than MAX_SURFACES should fail with ENOSPC."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        created = []
        for i in range(MAX_SURFACES + 5):
            status, sid, stride, total = s.surface_create(16, 16)

            if status == 0:
                created.append(sid)
            elif status == errno.ENOSPC:
                print(f"  Hit ENOSPC at surface {i+1} (created {len(created)})")
                break
            else:
                raise AssertionError(f"Unexpected status {status} at surface {i+1}")
        else:
            raise AssertionError(f"Should have hit limit, but created {len(created)} surfaces")

        assert len(created) <= MAX_SURFACES, f"Created {len(created)} > MAX_SURFACES"
        print(f"  Surface limit enforced: created {len(created)} before ENOSPC")


def test_event_queue_backpressure():
    """Event queue fills up, returns ENOSPC, then recovers after drain."""
    fd = os.open(DEV, os.O_RDWR)

    def read_one(fd):
        buf = os.read(fd, 4096)
        return parse_first_msg(buf)

    def hello(fd, frame_id, msg_id):
        payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(frame_id, [make_msg(REQ_HELLO, msg_id, payload)]))
        os.read(fd, 4096)

    def display_open(fd, frame_id, msg_id):
        payload = struct.pack("<I", 1)
        os.write(fd, make_frame(frame_id, [make_msg(0x0011, msg_id, payload)]))
        os.read(fd, 4096)

    def surface_create(fd, frame_id, msg_id, w, h):
        payload = struct.pack("<IIII", w, h, FMT_XRGB8888, 0)
        os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_CREATE, msg_id, payload)]))
        msg_type, _, payload = read_one(fd)
        assert msg_type == RPL_SURFACE_CREATE
        status, sid, stride, total = struct.unpack_from("<iIII", payload, 0)
        return status, sid

    def present_no_wait(fd, frame_id, msg_id, sid, cookie):
        """Present without reading events, just get reply status."""
        payload = struct.pack("<IIQ", sid, 0, cookie)
        os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_PRESENT, msg_id, payload)]))
        msg_type, _, payload = read_one(fd)
        if msg_type == RPL_SURFACE_PRESENT:
            status, = struct.unpack_from("<i", payload, 0)
            return status
        return -1

    try:
        hello(fd, 1, 1)
        display_open(fd, 2, 2)

        status, sid = surface_create(fd, 3, 3, 32, 32)
        assert status == 0

        # Spam presents without draining events to fill the queue
        hit_enospc = False
        frame_id = 10
        presents_before_enospc = 0

        for i in range(500):
            status = present_no_wait(fd, frame_id + i, 100 + i, sid, i)
            if status == errno.ENOSPC:
                hit_enospc = True
                presents_before_enospc = i
                break
            elif status != 0:
                raise AssertionError(f"Unexpected present status {status}")

        assert hit_enospc, "Expected to hit ENOSPC from event queue full"
        print(f"  Hit ENOSPC after {presents_before_enospc} presents")

        # Drain events
        p = select.poll()
        p.register(fd, select.POLLIN | select.POLLRDNORM)
        drained = 0

        while True:
            ev = p.poll(100)
            if not ev:
                break
            msg_type, _, _ = read_one(fd)
            if msg_type == EVT_SURFACE_PRESENTED:
                drained += 1

        print(f"  Drained {drained} events")

        # Should be able to present again
        status = present_no_wait(fd, 999, 999, sid, 0xDEADBEEF)
        assert status == 0, f"Present after drain failed: {status}"
        print(f"  Present after drain succeeded")

    finally:
        os.close(fd)


def test_stats_surface_tracking():
    """Stats correctly track surface count and bytes."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        stats0 = s.get_stats()
        assert stats0['surfaces_count'] == 0
        assert stats0['surfaces_bytes'] == 0

        # Create surface
        status, sid, stride, total = s.surface_create(64, 64)
        assert status == 0

        stats1 = s.get_stats()
        assert stats1['surfaces_count'] == 1, f"Expected 1 surface, got {stats1['surfaces_count']}"
        assert stats1['surfaces_bytes'] >= 64 * 64 * 4, f"surfaces_bytes too small"

        # Create another
        status, sid2, stride2, total2 = s.surface_create(128, 128)
        assert status == 0

        stats2 = s.get_stats()
        assert stats2['surfaces_count'] == 2
        assert stats2['surfaces_bytes'] > stats1['surfaces_bytes']

        # Destroy first
        s.surface_destroy(sid)

        stats3 = s.get_stats()
        assert stats3['surfaces_count'] == 1
        assert stats3['surfaces_bytes'] < stats2['surfaces_bytes']

        print(f"  Stats tracking verified: 0 -> 1 -> 2 -> 1 surfaces")


def test_stats_event_tracking():
    """Stats correctly track events enqueued."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        status, sid, stride, total = s.surface_create(32, 32)
        assert status == 0
        s.map_surface(sid)

        stats0 = s.get_stats()
        initial_events = stats0['events_enqueued']

        # Present 5 times
        for i in range(5):
            s.surface_present(sid, i)
            s.read_presented_event()

        stats1 = s.get_stats()
        new_events = stats1['events_enqueued'] - initial_events
        assert new_events >= 5, f"Expected at least 5 new events, got {new_events}"

        print(f"  Event tracking verified: {new_events} events enqueued")


def main():
    tests = [
        ("Oversized surface", test_oversized_surface),
        ("Max surfaces", test_max_surfaces),
        ("Event queue backpressure", test_event_queue_backpressure),
        ("Stats surface tracking", test_stats_surface_tracking),
        ("Stats event tracking", test_stats_event_tracking),
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
