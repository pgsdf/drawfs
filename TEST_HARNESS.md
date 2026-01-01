# TEST HARNESS

The drawfs test harness validates kernel behavior using black-box tests.

## Coverage
- Protocol correctness
- Error handling
- Blocking and poll behavior
- mmap lifecycle correctness

## Implementation
- Python protocol tests
- C ioctl tests
- Deterministic replay

Tests are designed to run without GPU hardware.
