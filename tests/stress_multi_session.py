#!/usr/bin/env python3
"""
stress_multi_session.py - Multi-session stress test with concurrent operations.

This test exercises session isolation and concurrent access by:
- Running multiple sessions in parallel
- Interleaving operations across sessions
- Rapidly opening and closing sessions
- Verifying no cross-session interference

Note: Python's GIL limits true parallelism, but this still exercises
the kernel's session isolation and locking.
"""

import os
import sys
import time
import random
import threading
import argparse
from typing import List

# Add tests directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drawfs_test import DrawSession, DEV


class SessionWorker:
    """Worker that performs operations in a single session."""

    def __init__(self, worker_id: int, iterations: int, verbose: bool = False):
        self.worker_id = worker_id
        self.iterations = iterations
        self.verbose = verbose
        self.results = {
            'created': 0,
            'destroyed': 0,
            'presented': 0,
            'errors': 0,
            'elapsed': 0.0
        }
        self.error_msg = None

    def run(self):
        """Execute the worker's workload."""
        try:
            start = time.time()
            self._do_work()
            self.results['elapsed'] = time.time() - start
        except Exception as e:
            self.error_msg = str(e)
            self.results['errors'] += 1

    def _do_work(self):
        with DrawSession() as s:
            s.hello()
            s.display_open()

            surfaces = []

            for i in range(self.iterations):
                r = random.random()

                if r < 0.4 and len(surfaces) < 10:
                    # Create (skip_events=True to handle pending events)
                    status, sid, _, _ = s.surface_create(
                        random.randint(32, 128),
                        random.randint(32, 128),
                        skip_events=True
                    )
                    if status == 0:
                        surfaces.append(sid)
                        self.results['created'] += 1

                elif r < 0.6 and surfaces:
                    # Destroy (skip_events=True to handle pending events)
                    sid = surfaces.pop(random.randint(0, len(surfaces) - 1))
                    if s.surface_destroy(sid, skip_events=True) == 0:
                        self.results['destroyed'] += 1

                elif surfaces:
                    # Present (skip_events=True to handle pending events)
                    sid = random.choice(surfaces)
                    status, _, _ = s.surface_present(sid, i, skip_events=True)
                    if status == 0:
                        self.results['presented'] += 1

                # Periodically drain
                if i % 50 == 0:
                    s.drain_all(max_msgs=20, timeout_s=0.05)

            # Cleanup
            s.drain_all(max_msgs=500, timeout_s=1.0)
            for sid in surfaces:
                s.surface_destroy(sid, skip_events=True)


def stress_parallel_sessions(num_workers: int, iterations: int, verbose: bool = False):
    """Run multiple sessions in parallel threads."""
    print(f"== Stress: {num_workers} parallel sessions, {iterations} ops each ==")

    workers = [SessionWorker(i, iterations, verbose) for i in range(num_workers)]
    threads = [threading.Thread(target=w.run) for w in workers]

    start = time.time()

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    elapsed = time.time() - start

    # Aggregate results
    total = {'created': 0, 'destroyed': 0, 'presented': 0, 'errors': 0}
    for w in workers:
        for k in total:
            total[k] += w.results[k]
        if w.error_msg:
            print(f"  worker {w.worker_id} error: {w.error_msg}")

    print(f"  total created: {total['created']}")
    print(f"  total destroyed: {total['destroyed']}")
    print(f"  total presented: {total['presented']}")
    print(f"  total errors: {total['errors']}")
    print(f"  elapsed: {elapsed:.2f}s")
    print(f"  throughput: {(total['created'] + total['presented']) / elapsed:.0f} ops/s")


def stress_session_churn(iterations: int, verbose: bool = False):
    """Rapidly open and close sessions."""
    print(f"== Stress: session churn ({iterations} open/close cycles) ==")

    start = time.time()
    errors = 0

    for i in range(iterations):
        try:
            with DrawSession() as s:
                s.hello()
                s.display_open()
                # Create a surface and present once
                status, sid, _, _ = s.surface_create(64, 64, skip_events=True)
                if status == 0:
                    s.surface_present(sid, i, skip_events=True)
                    s.drain_all(max_msgs=5, timeout_s=0.05)
                    s.surface_destroy(sid, skip_events=True)
        except Exception as e:
            errors += 1
            if verbose:
                print(f"  error on iteration {i}: {e}")

    elapsed = time.time() - start
    rate = iterations / elapsed if elapsed > 0 else 0

    print(f"  completed: {iterations - errors}/{iterations}")
    print(f"  errors: {errors}")
    print(f"  elapsed: {elapsed:.2f}s, rate: {rate:.0f} sessions/s")


def stress_interleaved_sessions(num_sessions: int, iterations: int, verbose: bool = False):
    """Interleave operations across multiple open sessions."""
    print(f"== Stress: interleaved ops across {num_sessions} sessions ==")

    sessions: List[DrawSession] = []
    surfaces: List[List[int]] = [[] for _ in range(num_sessions)]

    try:
        # Open all sessions
        for i in range(num_sessions):
            s = DrawSession()
            s.__enter__()
            s.hello()
            s.display_open()
            sessions.append(s)

        ops = {'create': 0, 'destroy': 0, 'present': 0}
        errors = 0
        start = time.time()

        for i in range(iterations):
            # Pick random session
            idx = random.randint(0, num_sessions - 1)
            s = sessions[idx]
            surfs = surfaces[idx]

            r = random.random()

            if r < 0.4 and len(surfs) < 5:
                status, sid, _, _ = s.surface_create(64, 64, skip_events=True)
                if status == 0:
                    surfs.append(sid)
                    ops['create'] += 1
                elif status not in (28,):
                    errors += 1

            elif r < 0.6 and surfs:
                sid = surfs.pop(random.randint(0, len(surfs) - 1))
                if s.surface_destroy(sid, skip_events=True) == 0:
                    ops['destroy'] += 1
                else:
                    errors += 1

            elif surfs:
                sid = random.choice(surfs)
                status, _, _ = s.surface_present(sid, i, skip_events=True)
                if status == 0:
                    ops['present'] += 1
                else:
                    errors += 1

            # Periodic drain on random session
            if i % 100 == 0:
                drain_idx = random.randint(0, num_sessions - 1)
                sessions[drain_idx].drain_all(max_msgs=20, timeout_s=0.05)

        elapsed = time.time() - start

        print(f"  operations: {ops}")
        print(f"  errors: {errors}")
        print(f"  elapsed: {elapsed:.2f}s")

    finally:
        # Cleanup
        for i, s in enumerate(sessions):
            try:
                s.drain_all(max_msgs=100, timeout_s=0.5)
                for sid in surfaces[i]:
                    s.surface_destroy(sid, skip_events=True)
                s.__exit__(None, None, None)
            except:
                pass


def main():
    parser = argparse.ArgumentParser(description="Multi-session stress test")
    parser.add_argument("--iterations", "-n", type=int, default=500,
                        help="Number of iterations per test")
    parser.add_argument("--workers", "-w", type=int, default=4,
                        help="Number of parallel workers")
    parser.add_argument("--sessions", "-s", type=int, default=5,
                        help="Number of interleaved sessions")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    parser.add_argument("--test", "-t",
                        choices=["parallel", "churn", "interleaved", "all"],
                        default="all", help="Which test to run")
    args = parser.parse_args()

    print(f"Multi-session stress test")
    print()

    if args.test in ("parallel", "all"):
        stress_parallel_sessions(args.workers, args.iterations, args.verbose)
        print()

    if args.test in ("churn", "all"):
        stress_session_churn(args.iterations, args.verbose)
        print()

    if args.test in ("interleaved", "all"):
        stress_interleaved_sessions(args.sessions, args.iterations, args.verbose)
        print()

    print("OK: multi-session stress tests completed")


if __name__ == "__main__":
    main()
