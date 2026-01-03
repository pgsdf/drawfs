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

### Optional but recommended work

1. Hardening and DoS resistance
   - Make conservative limits tunable via sysctl (per surface bytes, per session total bytes, max surface count)
   - Add a regression test for limits and for cleanup on close
   - Consider rate limiting event production to avoid unbounded out queue growth

2. Test ergonomics
   - Add a shared Python helper module for framing, request building, and event parsing to reduce drift across tests
   - Add a small debug tool to dump decoded frames from a raw read buffer

3. Code quality
   - Split protocol and validation logic into a dedicated C file to keep drawfs.c smaller
   - Run a consistent formatting pass (tabs for indentation, no mixed brace styles)
   - Add additional assertions and comments around locking rules

4. Security posture
   - Consider making the device node permissions and group ownership configurable
   - Consider a privileged ioctl or sysctl gate for enabling mmap

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

- Hardening: Make event queue and surface limits tunable via sysctl (per-session and global).
- Hardening: Add optional event coalescing for repeated SURFACE_PRESENTED events when userland is not draining quickly.
- Observability: Expose per-session counters (evq_bytes, evq_drops, surfaces_live) in stats ioctl.
- Correctness: Add regression tests that create/destroy/mmap/present surfaces under stress and verify no VM object leaks.
- Concurrency: Add a multi-threaded fuzzer that interleaves writes/reads/closes across multiple sessions.
- Compatibility: Confirm behavior on FreeBSD 15 with both debug and non-debug kernels.

3. Memory lifecycle validation
   - Add regression test that creates, mmaps, destroys many surfaces and checks for reclaimed VM objects (vmstat -m, vmstat -z) during CI
   - Add a debug sysctl counter for surface vm_object allocations and deallocations to catch leaks early

4. Event queue semantics
   - Clarify and enforce backpressure behavior: when the per session event queue is full, writes that would enqueue more output must fail with ENOSPC
   - Consider a future mode to drop events instead, but only if explicitly enabled and observable via stats
