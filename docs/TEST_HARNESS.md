# TEST HARNESS

The drawfs test harness validates kernel behavior using black box tests that talk to /dev/draw.

## Goals
- Protocol correctness
- Error handling
- Blocking read and poll behavior
- mmap lifecycle correctness
- Session lifecycle correctness (close, reopen, multi session isolation)

## Implementation
- Python protocol tests in tests/
- Small C tests for ioctl edge cases when useful
- Deterministic, hardware independent behavior (no GPU required)

## How to run
Build and load the module first:

    sudo ./build.sh all

Then run individual steps:

### Step 16
Multi session isolation.

    sudo python3 tests/step16_multi_session_isolation_test.py

### Step 17
Interleaved present across two sessions.

    sudo python3 tests/step17_multi_session_interleaved_present_test.py

### Step 18
Per session resource limits.

    sudo python3 tests/step18_surface_limits_test.py
