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
   - Make event queue and surface limits tunable via sysctl (per-session and global)

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

- Hardening: Add optional event coalescing for repeated SURFACE_PRESENTED events when userland is not draining quickly.
- Observability: Expose per-session counters (evq_bytes, evq_drops, surfaces_live) in stats ioctl.
- Correctness: Add regression tests that create/destroy/mmap/present surfaces under stress and verify no VM object leaks.
- Concurrency: Add a multi-threaded fuzzer that interleaves writes/reads/closes across multiple sessions.
- Compatibility: Confirm behavior on FreeBSD 15 with both debug and non-debug kernels.
- Memory lifecycle validation: Add regression test that creates, mmaps, destroys many surfaces and checks for reclaimed VM objects (vmstat -m, vmstat -z) during CI.
- Memory lifecycle validation: Add a debug sysctl counter for surface vm_object allocations and deallocations to catch leaks early.
