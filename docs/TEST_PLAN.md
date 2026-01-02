# TEST PLAN

## Goals
- Verify protocol compliance
- Ensure robustness against malformed input
- Guarantee deterministic behavior

## Test Types
- Unit tests (protocol parsing)
- Integration tests (kernel + user space)
- Stress and fuzz testing

## Current Focus
- Step 11 surface mmap correctness
- Lifetime and cleanup behavior
- Error propagation

## Step 13: Surface present sequencing

Run:

```
sudo python3 tests/step13_present_sequence_test.py
```

Validates reply and event ordering and cookie roundtrip.


## Step 14: Multi Surface Round Robin Present

Runs `tests/step14_multi_surface_round_robin_test.py` to validate creating multiple surfaces, writing distinct patterns via MAP_SURFACE plus mmap, and presenting in a round robin sequence while verifying reply and SURFACE_PRESENTED event ordering and cookies.

## Step 15: Session Cleanup and Reopen

Run:

```
sudo python3 tests/step15_session_cleanup_reopen_test.py
```

Validates that drawfs session state is per file descriptor and that close(2)
cleans up surfaces and mappings. After closing the fd, a new open must not be
able to map the old surface ID, and the next created surface ID should restart
from 1 in the new session.

## Step 16: Multi session isolation
Step 17: Multi session interleaved present (two fds presenting in alternating order) plus close and continue on remaining session.

Goal: verify that two independent sessions, meaning two open file descriptors, can create, map, and present surfaces without interfering with each other.

Test: `tests/step16_multi_session_isolation_test.py`

Expected: both sessions receive a `SURFACE_PRESENTED` event with the matching surface id and cookie for that session.