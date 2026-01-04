#!/usr/bin/env python3
"""
Test vm_object lifecycle counters via sysctl.

These tests verify that hw.drawfs.vmobj_allocs and hw.drawfs.vmobj_deallocs
correctly track vm_object allocations/deallocations for leak detection.
"""

import mmap
import subprocess
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from drawfs_test import DrawSession


def get_vmobj_counters():
    """Read vmobj_allocs and vmobj_deallocs from sysctl."""
    result = subprocess.run(
        ["sysctl", "-n", "hw.drawfs.vmobj_allocs", "hw.drawfs.vmobj_deallocs"],
        capture_output=True, text=True, check=True
    )
    lines = result.stdout.strip().split('\n')
    allocs = int(lines[0])
    deallocs = int(lines[1])
    return allocs, deallocs


def test_vmobj_counters_basic():
    """Verify counters increment on mmap and decrement on destroy."""
    print("== Test: vmobj counters track allocations ==")

    allocs_before, deallocs_before = get_vmobj_counters()
    print(f"  before: allocs={allocs_before}, deallocs={deallocs_before}")

    with DrawSession() as s:
        s.hello()
        s.display_open()

        # Create surface and select for mmap
        status, sid, stride, total = s.surface_create(64, 64)
        assert status == 0, f"surface_create failed: {status}"

        status, _, _, total_bytes = s.map_surface(sid)
        assert status == 0, f"map_surface failed: {status}"

        # Actual mmap() syscall triggers vm_pager_allocate
        mm = mmap.mmap(s.fd, total_bytes, mmap.MAP_SHARED,
                       mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            allocs_after_mmap, deallocs_after_mmap = get_vmobj_counters()
            print(f"  after mmap: allocs={allocs_after_mmap}, deallocs={deallocs_after_mmap}")
            assert allocs_after_mmap == allocs_before + 1, \
                f"Expected allocs to increase by 1, got {allocs_after_mmap - allocs_before}"
        finally:
            mm.close()

        # Destroy surface (triggers vm_object_deallocate)
        status = s.surface_destroy(sid)
        assert status == 0, f"surface_destroy failed: {status}"

        allocs_after_destroy, deallocs_after_destroy = get_vmobj_counters()
        print(f"  after destroy: allocs={allocs_after_destroy}, deallocs={deallocs_after_destroy}")
        assert deallocs_after_destroy == deallocs_after_mmap + 1, \
            f"Expected deallocs to increase by 1, got {deallocs_after_destroy - deallocs_after_mmap}"

    print("  OK")


def test_vmobj_counters_session_close():
    """Verify counters balance after session close with mmapped surfaces."""
    print("== Test: vmobj counters balance on session close ==")

    allocs_before, deallocs_before = get_vmobj_counters()
    live_before = allocs_before - deallocs_before
    print(f"  before: allocs={allocs_before}, deallocs={deallocs_before}, live={live_before}")

    # Create session, mmap surfaces, then close without explicit destroy
    with DrawSession() as s:
        s.hello()
        s.display_open()

        mmaps = []
        # Create and mmap 3 surfaces
        for i in range(3):
            status, sid, _, _ = s.surface_create(64, 64)
            assert status == 0
            status, _, _, total = s.map_surface(sid)
            assert status == 0
            mm = mmap.mmap(s.fd, total, mmap.MAP_SHARED,
                           mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
            mmaps.append(mm)

        allocs_during, deallocs_during = get_vmobj_counters()
        print(f"  during session: allocs={allocs_during}, deallocs={deallocs_during}")
        assert allocs_during == allocs_before + 3

        # Close all mmaps before session closes
        for mm in mmaps:
            mm.close()

    # Session closed - all surfaces should be cleaned up
    allocs_after, deallocs_after = get_vmobj_counters()
    live_after = allocs_after - deallocs_after
    print(f"  after close: allocs={allocs_after}, deallocs={deallocs_after}, live={live_after}")

    assert live_after == live_before, \
        f"Leak detected: live objects changed from {live_before} to {live_after}"

    print("  OK")


def test_vmobj_counters_no_mmap():
    """Verify no allocation if surface is never mmapped."""
    print("== Test: no vmobj allocation without mmap ==")

    allocs_before, deallocs_before = get_vmobj_counters()
    print(f"  before: allocs={allocs_before}, deallocs={deallocs_before}")

    with DrawSession() as s:
        s.hello()
        s.display_open()

        # Create surface but don't mmap
        status, sid, _, _ = s.surface_create(64, 64)
        assert status == 0

        allocs_after_create, _ = get_vmobj_counters()
        print(f"  after create (no mmap): allocs={allocs_after_create}")
        assert allocs_after_create == allocs_before, \
            "vmobj allocated without mmap"

        # Destroy without mmap
        status = s.surface_destroy(sid)
        assert status == 0

    allocs_after, deallocs_after = get_vmobj_counters()
    print(f"  after destroy: allocs={allocs_after}, deallocs={deallocs_after}")
    assert allocs_after == allocs_before
    assert deallocs_after == deallocs_before

    print("  OK")


def test_vmobj_counters_multiple_surfaces():
    """Verify counters with multiple mmapped surfaces."""
    print("== Test: vmobj counters with multiple surfaces ==")

    allocs_before, deallocs_before = get_vmobj_counters()
    print(f"  before: allocs={allocs_before}, deallocs={deallocs_before}")

    with DrawSession() as s:
        s.hello()
        s.display_open()

        surfaces = []
        mmaps = []
        for i in range(5):
            status, sid, _, _ = s.surface_create(64, 64)
            assert status == 0
            status, _, _, total = s.map_surface(sid)
            assert status == 0
            mm = mmap.mmap(s.fd, total, mmap.MAP_SHARED,
                           mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
            surfaces.append(sid)
            mmaps.append(mm)

        allocs_after_mmap, _ = get_vmobj_counters()
        print(f"  after 5 mmaps: allocs={allocs_after_mmap}")
        assert allocs_after_mmap == allocs_before + 5

        # Close mmaps for surfaces we're about to destroy
        for mm in mmaps[:3]:
            mm.close()

        # Destroy 3 surfaces
        for sid in surfaces[:3]:
            s.surface_destroy(sid)

        _, deallocs_after_destroy = get_vmobj_counters()
        print(f"  after destroying 3: deallocs={deallocs_after_destroy}")
        assert deallocs_after_destroy == deallocs_before + 3

        # Close remaining mmaps
        for mm in mmaps[3:]:
            mm.close()

    # Session close cleans up remaining 2
    allocs_after, deallocs_after = get_vmobj_counters()
    print(f"  after session close: allocs={allocs_after}, deallocs={deallocs_after}")
    assert deallocs_after == deallocs_before + 5
    assert allocs_after - deallocs_after == allocs_before - deallocs_before

    print("  OK")


def main():
    print("vm_object lifecycle counter tests")
    print("(requires hw.drawfs.vmobj_allocs/deallocs sysctls)")
    print()

    try:
        get_vmobj_counters()
    except subprocess.CalledProcessError:
        print("ERROR: Cannot read vmobj sysctls. Is the module loaded?")
        sys.exit(1)

    test_vmobj_counters_no_mmap()
    print()

    test_vmobj_counters_basic()
    print()

    test_vmobj_counters_session_close()
    print()

    test_vmobj_counters_multiple_surfaces()
    print()

    print("OK: all vmobj counter tests passed")


if __name__ == "__main__":
    main()
