# ROADMAP

This document is a forward-looking backlog for drawfs. Items are grouped by priority and include optional hardening work we want to keep visible.

## Near term

### Step 18: Resource limits and hardening
- Enforce per-session surface limits in SURFACE_CREATE and return ENOSPC when a limit is hit.
- Ensure all surfaces release their VM objects on destroy and on session teardown (vm_object_deallocate).
- Add a regression test that proves the limit is deterministic and does not fall back to ENOMEM.
- Confirm the MAP_SURFACE selection and mmap path cannot cross sessions.

## Next

### Protocol and ABI
- Add explicit protocol version negotiation and a feature bitmask in HELLO.
- Document all message and event payloads with exact sizes and alignment.
- Add negative tests for malformed frames and messages (lengths, alignment, unknown types).

### Observability
- Add a lightweight stats ioctl for surface limits, current usage, and event queue depth.
- Add optional debug logging behind a compile-time flag.

## Optional but recommended

### Tunables and policy
- Make surface limits tunable via sysctl (read only by default) and document safe defaults.
- Consider per-process caps using credentials or devfs rules if multi-user scenarios matter.

### Robustness
- Add fuzzing of the frame parser and message decoder (kcov, syzkaller style harness, or userland fuzz against a mock).
- Add lock order notes and ASSERTs for invariants in debug builds.
- Expand tests to cover close during blocking read, close during poll, and close while a surface is selected for mmap.

### Cleanup
- Style pass: consistent indentation, brace placement, and removing unreachable code.
- Split drawfs.c into smaller translation units (protocol, surfaces, events, ioctl, mmap) when the API stabilizes.
