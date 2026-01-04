# ROADMAP

## Phase 0: Specification
- Protocol definition
- State machines
- Error semantics
- Test harness

## Phase 1: Kernel Prototype (current)
- Character device protocol
- Blocking reads and poll semantics
- Display discovery and open
- Surface lifecycle
- mmap-backed surface memory
- Event queue backpressure (Step 19)
- Surface resource limits (Step 18)

### Completed work

1. Hardening and DoS resistance
   - [x] Surface size limits (EFBIG for >64MB surfaces)
   - [x] Per-session surface count limits (ENOSPC after 64 surfaces)
   - [x] Event queue backpressure (ENOSPC when queue full, recovery after drain)
   - [x] Regression tests for limits (Step 18, Step 19)

2. Test ergonomics
   - [x] Shared Python helper module (`tests/drawfs_test.py`) for framing, request building, and event parsing
   - [x] DrawSession context manager for cleaner test code
   - [x] Select-based reads to avoid indefinite blocking
   - [x] Debug tool to dump decoded frames from raw read buffer (tests/drawfs_dump.py)

### Remaining optional work

1. Code quality
   - [x] Split protocol and validation logic into dedicated C files (drawfs_frame.c, drawfs_surface.c)
   - [x] Verified consistent formatting (tabs for indentation, BSD brace style)
   - [x] Added locking rule comments to drawfs.c and drawfs_surface.c

2. Security posture
   - [x] Device node permissions configurable via sysctl (hw.drawfs.dev_uid/gid/mode)
   - [x] mmap gated by sysctl (hw.drawfs.mmap_enabled)

3. Tuning
   - [x] Event queue and surface limits tunable via sysctl (hw.drawfs.max_*)

## Phase 2: Real Display Bring-up
- DRM/KMS integration
- Mode setting
- Atomic present path

## Phase 3: User Environment
- Reference compositor
- Window management
- Input integration

## Phase 4: Optimization
- Zero-copy paths
- GPU acceleration
- Scheduling and batching

## Backlog

### Completed

- [x] Hardening: Event coalescing for repeated SURFACE_PRESENTED events (hw.drawfs.coalesce_events)
- [x] Correctness: Stress tests for surface lifecycle (stress_surface_lifecycle.py)
- [x] Concurrency: Multi-session stress tests with parallel/interleaved operations (stress_multi_session.py)
- [x] Memory lifecycle: Validation tests using vmstat -m (test_memory_lifecycle.py)
- [x] Observability: Expose per-session counters (evq_bytes, surfaces_count, surfaces_bytes) in stats ioctl (test_observability.py)
- [x] Compatibility: Verified on FreeBSD 15.0-RELEASE-p1 (non-debug kernel) - all tests pass
- [x] Memory lifecycle validation: Debug sysctl counters for vm_object tracking (hw.drawfs.vmobj_allocs/deallocs, test_vmobj_counters.py)

### Remaining

- Compatibility: Test on FreeBSD 15 debug kernel (WITNESS enabled) when available.
