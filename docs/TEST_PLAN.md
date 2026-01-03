# TEST PLAN

## Goals
- Verify protocol compliance
- Ensure robustness against malformed input
- Guarantee deterministic behavior
- Validate resource limits and backpressure

## Test Types
- Unit tests (protocol parsing)
- Integration tests (kernel + user space)
- Stress and fuzz testing

## Shared Test Module

All tests use the shared `tests/drawfs_test.py` module for consistent protocol encoding.
See `docs/TEST_HARNESS.md` for full API documentation.

## Test Steps

### Step 6-9: Protocol Basics
- Step 6: Multi-message frames and poll readiness
- Step 7B: Stats ioctl with protocol traffic
- Step 8: DISPLAY_LIST reply decoding
- Step 9: DISPLAY_OPEN for valid and invalid display IDs

### Step 10-11: Surface Lifecycle
- Step 10A: SURFACE_CREATE lifecycle and error cases
- Step 10B: SURFACE_DESTROY and double-destroy errors
- Step 11: MAP_SURFACE ioctl and mmap write/readback

### Step 12-14: Present Path
- Step 12: End-to-end present flow with mmap and event
- Step 13: Present sequencing and cookie roundtrip
- Step 14: Multiple surfaces with round-robin presents

### Step 15-17: Session Management
- Step 15: Per-fd session state and cleanup on close
- Step 16: Two sessions with independent surfaces
- Step 17: Interleaved presents across sessions, close and continue

### Step 18-19: Resource Limits
- Step 18: EFBIG for oversized surfaces, ENOSPC for too many surfaces
- Step 19: Event queue backpressure (ENOSPC when full, recovery after drain)

## Running Tests

Individual test:
```sh
sudo python3 tests/step13_present_sequence_test.py
```

All tests:
```sh
./build.sh test
```

## Current Status

All steps (6-19) are implemented and passing.
