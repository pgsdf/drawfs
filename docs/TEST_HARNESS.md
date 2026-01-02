# TEST HARNESS

The drawfs test harness validates kernel behavior using black-box tests.

## Coverage
- Protocol correctness
- Error handling
- Blocking and poll behavior
- mmap lifecycle correctness
- Session lifecycle correctness (close and reopen)

## Implementation
- Python protocol tests
- C ioctl tests
- Deterministic replay

Tests are designed to run without GPU hardware.

### Step 16

Run:

    sudo python3 tests/step16_multi_session_isolation_test.py

