#!/usr/bin/env python3
"""
Test observability stats: evq_bytes, surfaces_count, surfaces_bytes.

These tests verify that the stats ioctl correctly reports current
resource usage for debugging and monitoring.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from drawfs_test import DrawSession


def test_surfaces_count():
    """Verify surfaces_count tracks live surfaces."""
    print("== Test: surfaces_count tracks live surfaces ==")

    with DrawSession() as s:
        s.hello()
        s.display_open()

        stats = s.get_stats()
        assert stats['surfaces_count'] == 0, f"Expected 0 surfaces, got {stats['surfaces_count']}"
        print(f"  initial surfaces_count: {stats['surfaces_count']}")

        # Create 5 surfaces
        surfaces = []
        for i in range(5):
            status, sid, _, _ = s.surface_create(64, 64)
            assert status == 0, f"surface_create failed: {status}"
            surfaces.append(sid)

        stats = s.get_stats()
        assert stats['surfaces_count'] == 5, f"Expected 5 surfaces, got {stats['surfaces_count']}"
        print(f"  after creating 5: surfaces_count={stats['surfaces_count']}")

        # Destroy 2 surfaces
        for sid in surfaces[:2]:
            status = s.surface_destroy(sid)
            assert status == 0, f"surface_destroy failed: {status}"

        stats = s.get_stats()
        assert stats['surfaces_count'] == 3, f"Expected 3 surfaces, got {stats['surfaces_count']}"
        print(f"  after destroying 2: surfaces_count={stats['surfaces_count']}")

        # Cleanup
        for sid in surfaces[2:]:
            s.surface_destroy(sid)

        stats = s.get_stats()
        assert stats['surfaces_count'] == 0, f"Expected 0 surfaces, got {stats['surfaces_count']}"
        print(f"  after cleanup: surfaces_count={stats['surfaces_count']}")

    print("  OK")


def test_surfaces_bytes():
    """Verify surfaces_bytes tracks total surface memory."""
    print("== Test: surfaces_bytes tracks surface memory ==")

    with DrawSession() as s:
        s.hello()
        s.display_open()

        stats = s.get_stats()
        assert stats['surfaces_bytes'] == 0, f"Expected 0 bytes, got {stats['surfaces_bytes']}"
        print(f"  initial surfaces_bytes: {stats['surfaces_bytes']}")

        # Create a 100x100 XRGB8888 surface (4 bytes/pixel = 40000 bytes minimum)
        status, sid1, stride1, total1 = s.surface_create(100, 100)
        assert status == 0, f"surface_create failed: {status}"
        print(f"  created 100x100 surface: stride={stride1}, total={total1}")

        stats = s.get_stats()
        assert stats['surfaces_bytes'] == total1, \
            f"Expected {total1} bytes, got {stats['surfaces_bytes']}"
        print(f"  surfaces_bytes: {stats['surfaces_bytes']}")

        # Create another surface
        status, sid2, stride2, total2 = s.surface_create(200, 200)
        assert status == 0, f"surface_create failed: {status}"
        print(f"  created 200x200 surface: stride={stride2}, total={total2}")

        stats = s.get_stats()
        expected = total1 + total2
        assert stats['surfaces_bytes'] == expected, \
            f"Expected {expected} bytes, got {stats['surfaces_bytes']}"
        print(f"  surfaces_bytes: {stats['surfaces_bytes']}")

        # Destroy first surface
        s.surface_destroy(sid1)
        stats = s.get_stats()
        assert stats['surfaces_bytes'] == total2, \
            f"Expected {total2} bytes, got {stats['surfaces_bytes']}"
        print(f"  after destroying first: surfaces_bytes={stats['surfaces_bytes']}")

        # Cleanup
        s.surface_destroy(sid2)
        stats = s.get_stats()
        assert stats['surfaces_bytes'] == 0, f"Expected 0 bytes, got {stats['surfaces_bytes']}"
        print(f"  after cleanup: surfaces_bytes={stats['surfaces_bytes']}")

    print("  OK")


def test_evq_bytes():
    """Verify evq_bytes tracks event queue size."""
    print("== Test: evq_bytes tracks event queue size ==")

    with DrawSession() as s:
        s.hello()
        s.display_open()

        # Create a surface and present to generate events
        status, sid, _, _ = s.surface_create(64, 64)
        assert status == 0

        stats = s.get_stats()
        initial_evq = stats['evq_bytes']
        print(f"  initial evq_bytes: {initial_evq}")

        # Present generates a SURFACE_PRESENTED event
        status, _, _ = s.surface_present(sid, 12345)
        assert status == 0

        stats = s.get_stats()
        after_present = stats['evq_bytes']
        print(f"  after present evq_bytes: {after_present}")
        # Event should be in queue (frame_hdr=16 + msg_hdr=16 + payload=16 = 48 bytes)
        assert after_present > initial_evq, \
            f"Expected evq_bytes to increase after present"

        # Drain the event
        s.drain_all(max_msgs=10, timeout_s=1.0)

        stats = s.get_stats()
        after_drain = stats['evq_bytes']
        print(f"  after drain evq_bytes: {after_drain}")
        assert after_drain == 0, f"Expected 0 after drain, got {after_drain}"

        # Cleanup
        s.surface_destroy(sid)

    print("  OK")


def test_all_stats_present():
    """Verify all expected stats fields are present."""
    print("== Test: all stats fields present ==")

    with DrawSession() as s:
        s.hello()

        stats = s.get_stats()
        required_fields = [
            'frames_received', 'frames_processed', 'frames_invalid',
            'messages_processed', 'messages_unsupported',
            'events_enqueued', 'events_dropped',
            'bytes_in', 'bytes_out',
            'evq_depth', 'inbuf_bytes',
            'evq_bytes', 'surfaces_count', 'surfaces_bytes'
        ]

        for field in required_fields:
            assert field in stats, f"Missing stats field: {field}"
            print(f"  {field}: {stats[field]}")

    print("  OK")


def main():
    print("Observability stats tests")
    print()

    test_all_stats_present()
    print()

    test_surfaces_count()
    print()

    test_surfaces_bytes()
    print()

    test_evq_bytes()
    print()

    print("OK: all observability tests passed")


if __name__ == "__main__":
    main()
