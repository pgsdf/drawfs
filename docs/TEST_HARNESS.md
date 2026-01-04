# TEST HARNESS

The drawfs test harness validates kernel behavior using black-box tests.

## Coverage

- Protocol correctness
- Error handling
- Blocking and poll behavior
- mmap lifecycle correctness
- Session lifecycle correctness (close and reopen)
- Multi-session isolation
- Resource limits and backpressure

## Shared Test Infrastructure

All Python tests use the shared `tests/drawfs_test.py` module which provides:

### Protocol Constants
- `DRAWFS_MAGIC`, `DRAWFS_VERSION`
- Request types: `REQ_HELLO`, `REQ_DISPLAY_LIST`, `REQ_DISPLAY_OPEN`, `REQ_SURFACE_CREATE`, `REQ_SURFACE_DESTROY`, `REQ_SURFACE_PRESENT`
- Reply types: `RPL_OK`, `RPL_HELLO`, `RPL_DISPLAY_LIST`, `RPL_DISPLAY_OPEN`, `RPL_SURFACE_CREATE`, `RPL_SURFACE_DESTROY`, `RPL_SURFACE_PRESENT`, `RPL_ERROR`
- Event types: `EVT_SURFACE_PRESENTED`
- Pixel formats: `FMT_XRGB8888`

### Frame/Message Building
- `make_msg(msg_type, msg_id, payload)` - Build a single message
- `make_frame(frame_id, msgs)` - Build a frame containing messages
- `align4(n)` - Align value to 4-byte boundary

### Frame Parsing
- `parse_frame_header(data)` - Parse frame header
- `parse_msg_header(data, offset)` - Parse message header
- `parse_first_msg(frame)` - Parse first message from frame

### Read Utilities
- `read_frame(fd, timeout_ms)` - Read one frame with select-based timeout
- `read_msg(fd, timeout_ms)` - Read and parse first message
- `drain_until(fd, msg_type, ...)` - Read until specific message type
- `drain_all(fd, max_msgs, timeout_s)` - Drain all available messages

### Common Operations
- `hello(fd, frame_id, msg_id)` - Send HELLO and read reply
- `display_list(fd, ...)` - Send DISPLAY_LIST
- `display_open(fd, display_id, ...)` - Send DISPLAY_OPEN
- `surface_create(fd, width, height, ...)` - Create surface
- `surface_destroy(fd, surface_id, ...)` - Destroy surface
- `surface_present(fd, surface_id, cookie, ...)` - Present surface
- `read_presented_event(fd, ...)` - Read SURFACE_PRESENTED event

### ioctl Helpers
- `get_stats(fd)` - Get session statistics via DRAWFSGIOC_STATS
- `map_surface(fd, surface_id)` - Select surface for mmap via DRAWFSGIOC_MAP_SURFACE

### DrawSession Context Manager

For cleaner test code, use the `DrawSession` class:

```python
from drawfs_test import DrawSession

with DrawSession() as s:
    s.hello()
    s.display_open()
    status, sid, stride, total = s.surface_create(256, 256)
    st, sid2, stride2, total2 = s.map_surface(sid)
    status, rep_sid, cookie = s.surface_present(sid, 0x1234)
    ev_sid, ev_reserved, ev_cookie = s.read_presented_event()
```

## Debug Tool

The `tests/drawfs_dump.py` tool decodes raw frame data for debugging protocol issues:

```sh
# Decode hex-encoded frame from command line
./tests/drawfs_dump.py 44525731000110002c00000001000000...

# Decode binary frame from stdin
cat frame.bin | ./tests/drawfs_dump.py

# Decode hex from stdin
echo "44525731..." | ./tests/drawfs_dump.py --hex

# Live capture from device (requires root)
sudo ./tests/drawfs_dump.py --live --count 5
```

Example output:
```
=== Frame 1 (56 bytes) ===

Frame Header:
  magic:        0x31575244 ('DRW1') [OK]
  version:      0x0100 (1.0)
  header_bytes: 16
  frame_bytes:  56
  frame_id:     2

Message 1:
  offset:     16
  msg_type:   0x8010 (RPL_DISPLAY_LIST)
  msg_bytes:  40
  msg_id:     202
  payload (24 bytes):
    display_count: 1
      display[0]: id=1 1920x1080 @ 60.0Hz flags=0x0
```

## Test Steps

### Step 6: Multi-message and Poll
`tests/step6_multimsg_and_poll.py` - Validates multi-message frames and poll readiness.

### Step 7B: Stats on Same FD
`tests/step7B_stats_same_fd.py` - Validates stats ioctl with protocol traffic.

### Step 8: Display List Decode
`tests/step8_display_list_decode.py` - Validates DISPLAY_LIST reply decoding.

### Step 9: Display Open
`tests/step9_open_display_test.py` - Validates DISPLAY_OPEN for valid and invalid display IDs.

### Step 10A: Surface Create
`tests/step10A_surface_create_test.py` - Validates SURFACE_CREATE lifecycle and error cases.

### Step 10B: Surface Destroy
`tests/step10B_surface_destroy_test.py` - Validates SURFACE_DESTROY and double-destroy errors.

### Step 11: Surface mmap
`tests/step11_surface_mmap_test.py` - Validates MAP_SURFACE ioctl and mmap write/readback.

### Step 12: Surface Present
`tests/step12_surface_present_test.py` - End-to-end present flow with mmap and event.

### Step 13: Present Sequence
`tests/step13_present_sequence_test.py` - Validates present sequencing and cookie roundtrip.

### Step 14: Multi-surface Round Robin
`tests/step14_multi_surface_round_robin_test.py` - Multiple surfaces with round-robin presents.

### Step 15: Session Cleanup and Reopen
`tests/step15_session_cleanup_reopen_test.py` - Validates per-fd session state and cleanup.

### Step 16: Multi-session Isolation
`tests/step16_multi_session_isolation_test.py` - Two sessions with independent surfaces.

### Step 17: Multi-session Interleaved Present
`tests/step17_multi_session_interleaved_present_test.py` - Interleaved presents across sessions.

### Step 18: Surface Limits
`tests/step18_surface_limits_test.py` - Validates EFBIG for oversized surfaces and ENOSPC for too many surfaces.

### Step 19: Event Queue Backpressure
`tests/step19_event_queue_backpressure_test.py` - Validates ENOSPC when event queue is full and recovery after draining.

## Stress Tests

### Surface Lifecycle Stress
`tests/stress_surface_lifecycle.py` - Rapid surface create/destroy/present cycles.

```sh
sudo python3 tests/stress_surface_lifecycle.py -n 1000
sudo python3 tests/stress_surface_lifecycle.py -t present -n 5000
sudo python3 tests/stress_surface_lifecycle.py -t mixed -n 2000
```

### Multi-Session Stress
`tests/stress_multi_session.py` - Concurrent operations across multiple sessions.

```sh
sudo python3 tests/stress_multi_session.py -w 4 -n 500  # 4 parallel workers
sudo python3 tests/stress_multi_session.py -t churn -n 200  # session open/close
sudo python3 tests/stress_multi_session.py -t interleaved -s 5  # 5 interleaved sessions
```

### Memory Lifecycle Validation
`tests/test_memory_lifecycle.py` - Validates memory release using vmstat -m.

```sh
sudo python3 tests/test_memory_lifecycle.py -n 100
sudo python3 tests/test_memory_lifecycle.py -t churn -n 500
```

### Observability Stats
`tests/test_observability.py` - Validates stats ioctl observability fields.

Tests that `evq_bytes`, `surfaces_count`, and `surfaces_bytes` correctly track
current resource usage in real-time.

```sh
sudo python3 tests/test_observability.py
```

### VM Object Counters
`tests/test_vmobj_counters.py` - Validates vm_object lifecycle tracking.

Tests that `hw.drawfs.vmobj_allocs` and `hw.drawfs.vmobj_deallocs` correctly
track vm_object allocations/deallocations for leak detection.

```sh
sudo python3 tests/test_vmobj_counters.py
```

## Running Tests

Individual test:
```sh
sudo python3 tests/step12_surface_present_test.py
```

All tests via build script:
```sh
./build.sh test
```

## Implementation Notes

- Tests are designed to run without GPU hardware
- All tests use select-based reads to avoid indefinite blocking
- The shared module ensures consistent protocol encoding across all tests
- Stress tests exercise kernel locking and resource management under load
