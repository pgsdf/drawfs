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
