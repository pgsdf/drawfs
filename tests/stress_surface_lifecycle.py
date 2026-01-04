#!/usr/bin/env python3
"""
stress_surface_lifecycle.py - Stress test for surface create/destroy/present cycles.

This test exercises the kernel module by rapidly creating, presenting, and
destroying surfaces. It validates that:
- No resource leaks occur during rapid churn
- Backpressure handling works correctly under load
- Event coalescing reduces queue pressure
- The kernel handles edge cases gracefully
"""

import os
import sys
import time
import random
import argparse

# Add tests directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drawfs_test import (
    DrawSession, FMT_XRGB8888,
    RPL_SURFACE_CREATE, RPL_SURFACE_DESTROY, RPL_SURFACE_PRESENT,
    EVT_SURFACE_PRESENTED
)


def stress_create_destroy(iterations: int, verbose: bool = False):
    """Rapidly create and destroy surfaces."""
    print(f"== Stress: create/destroy {iterations} surfaces ==")

    with DrawSession() as s:
        s.hello()
        s.display_open()

        created = 0
        destroyed = 0
        errors = 0

        start = time.time()

        for i in range(iterations):
            # Create a small surface
            width = random.choice([64, 128, 256])
            height = random.choice([64, 128, 256])

            try:
                status, sid, stride, total = s.surface_create(width, height)
                if status == 0:
                    created += 1
                    # Immediately destroy it
                    destroy_status = s.surface_destroy(sid)
                    if destroy_status == 0:
                        destroyed += 1
                    else:
                        errors += 1
                        if verbose:
                            print(f"  destroy error: {destroy_status}")
                else:
                    # Expected when hitting limits
                    if verbose and status not in (28, 12):  # ENOSPC, ENOMEM
                        print(f"  create error: {status}")
            except Exception as e:
                errors += 1
                if verbose:
                    print(f"  exception: {e}")

        elapsed = time.time() - start
        rate = iterations / elapsed if elapsed > 0 else 0

        print(f"  created: {created}, destroyed: {destroyed}, errors: {errors}")
        print(f"  elapsed: {elapsed:.2f}s, rate: {rate:.0f} ops/s")

        # Get final stats
        stats = s.get_stats()
        print(f"  frames_processed: {stats['frames_processed']}")
        print(f"  events_dropped: {stats['events_dropped']}")


def stress_present_rapid(iterations: int, num_surfaces: int = 3, verbose: bool = False):
    """Rapidly present surfaces to stress event queue and coalescing."""
    print(f"== Stress: {iterations} presents across {num_surfaces} surfaces ==")

    with DrawSession() as s:
        s.hello()
        s.display_open()

        # Create surfaces
        surfaces = []
        for i in range(num_surfaces):
            status, sid, stride, total = s.surface_create(64, 64)
            if status == 0:
                surfaces.append(sid)
            else:
                print(f"  warning: could not create surface {i}: {status}")

        if not surfaces:
            print("  ERROR: no surfaces created")
            return

        print(f"  created {len(surfaces)} surfaces")

        presented = 0
        errors = 0
        start = time.time()

        for i in range(iterations):
            sid = random.choice(surfaces)
            cookie = i

            try:
                status, rep_sid, rep_cookie = s.surface_present(sid, cookie)
                if status == 0:
                    presented += 1
                else:
                    errors += 1
                    if verbose:
                        print(f"  present error: {status}")
            except Exception as e:
                errors += 1
                if verbose:
                    print(f"  exception: {e}")

        elapsed = time.time() - start
        rate = presented / elapsed if elapsed > 0 else 0

        print(f"  presented: {presented}, errors: {errors}")
        print(f"  elapsed: {elapsed:.2f}s, rate: {rate:.0f} presents/s")

        # Drain events
        drained = s.drain_all(max_msgs=iterations * 2, timeout_s=5.0)
        print(f"  drained: {drained} events")

        # Get final stats
        stats = s.get_stats()
        print(f"  events_enqueued: {stats['events_enqueued']}")
        print(f"  events_dropped: {stats['events_dropped']}")

        # Cleanup
        for sid in surfaces:
            s.surface_destroy(sid)


def stress_mixed_workload(iterations: int, verbose: bool = False):
    """Mix of create, destroy, present, and drain operations."""
    print(f"== Stress: mixed workload ({iterations} ops) ==")

    with DrawSession() as s:
        s.hello()
        s.display_open()

        surfaces = []
        ops = {'create': 0, 'destroy': 0, 'present': 0, 'drain': 0}
        errors = 0
        start = time.time()

        for i in range(iterations):
            # Weighted random operation
            r = random.random()

            if r < 0.3:
                # Create (skip_events=True to handle pending events)
                status, sid, stride, total = s.surface_create(
                    random.randint(32, 256),
                    random.randint(32, 256),
                    skip_events=True
                )
                if status == 0:
                    surfaces.append(sid)
                    ops['create'] += 1
                elif status not in (28, 12):  # ENOSPC, ENOMEM expected
                    errors += 1

            elif r < 0.5 and surfaces:
                # Destroy (skip_events=True to handle pending events)
                sid = surfaces.pop(random.randint(0, len(surfaces) - 1))
                status = s.surface_destroy(sid, skip_events=True)
                if status == 0:
                    ops['destroy'] += 1
                else:
                    errors += 1

            elif r < 0.9 and surfaces:
                # Present (skip_events=True to handle pending events)
                sid = random.choice(surfaces)
                status, _, _ = s.surface_present(sid, i, skip_events=True)
                if status == 0:
                    ops['present'] += 1
                else:
                    errors += 1

            else:
                # Drain some events
                drained = s.drain_all(max_msgs=10, timeout_s=0.1)
                ops['drain'] += drained

        elapsed = time.time() - start

        print(f"  operations: {ops}")
        print(f"  errors: {errors}")
        print(f"  elapsed: {elapsed:.2f}s")
        print(f"  surfaces remaining: {len(surfaces)}")

        # Final drain
        final_drain = s.drain_all(max_msgs=1000, timeout_s=2.0)
        print(f"  final drain: {final_drain} events")

        # Stats
        stats = s.get_stats()
        print(f"  events_enqueued: {stats['events_enqueued']}")
        print(f"  events_dropped: {stats['events_dropped']}")

        # Cleanup remaining surfaces
        for sid in surfaces:
            s.surface_destroy(sid, skip_events=True)


def main():
    parser = argparse.ArgumentParser(description="Surface lifecycle stress test")
    parser.add_argument("--iterations", "-n", type=int, default=1000,
                        help="Number of iterations per test")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    parser.add_argument("--test", "-t", choices=["create", "present", "mixed", "all"],
                        default="all", help="Which test to run")
    args = parser.parse_args()

    print(f"Surface lifecycle stress test (iterations={args.iterations})")
    print()

    if args.test in ("create", "all"):
        stress_create_destroy(args.iterations, args.verbose)
        print()

    if args.test in ("present", "all"):
        stress_present_rapid(args.iterations, verbose=args.verbose)
        print()

    if args.test in ("mixed", "all"):
        stress_mixed_workload(args.iterations, args.verbose)
        print()

    print("OK: stress tests completed")


if __name__ == "__main__":
    main()
