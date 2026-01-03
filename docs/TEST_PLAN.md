# TEST PLAN

This plan tracks the incremental kernel features validated by the tests in tests/.

## Step 11: Surface mmap
- Create a surface
- Select it for mmap using DRAWFSGIOC_MAP_SURFACE
- mmap the device and verify read and write works

Test:
    sudo python3 tests/step11_surface_mmap_test.py

## Step 12: Surface present
- Present a surface and receive a SURFACE_PRESENT reply
- Receive a SURFACE_PRESENTED event with the same cookie

Test:
    sudo python3 tests/step12_surface_present_test.py

## Step 13: Present sequencing
- Validate ordering and event typing
- Ensure SURFACE_PRESENTED is emitted in the expected sequence

Test:
    sudo python3 tests/step13_present_sequence_test.py

## Step 14: Multi surface round robin
- Create multiple surfaces and present them in a round robin loop

Test:
    sudo python3 tests/step14_multi_surface_round_robin_test.py

## Step 15: Session cleanup and reopen
- Create and present once
- Close the fd and ensure session teardown cleans resources
- Reopen and repeat

Test:
    sudo python3 tests/step15_session_cleanup_reopen_test.py

## Step 16: Multi session isolation
- Two sessions create their own surfaces
- Present on each session and ensure events are not cross delivered

Test:
    sudo python3 tests/step16_multi_session_isolation_test.py

## Step 17: Multi session interleaved present
- Two sessions interleave present operations
- Validate per session ordering and event isolation

Test:
    sudo python3 tests/step17_multi_session_interleaved_present_test.py

## Step 18: Resource limits
- Repeatedly create surfaces until the per session limit is hit
- Expect ENOSPC once the limit is exceeded
- Ensure no fallback to ENOMEM due to swap exhaustion

Test:
    sudo python3 tests/step18_surface_limits_test.py
