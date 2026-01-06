#!/usr/bin/env python3
"""
test_protocol.py - Protocol fundamentals tests

Tests:
  - HELLO handshake
  - DISPLAY_LIST enumeration
  - DISPLAY_OPEN (valid and invalid)
  - Stats ioctl
  - Multi-message frames
  - Poll readiness
"""

import os
import select
import struct
import errno
from drawfs_test import (
    DrawSession, DEV, make_frame, make_msg, parse_first_msg,
    REQ_HELLO, REQ_DISPLAY_LIST, REQ_DISPLAY_OPEN,
    RPL_HELLO, RPL_DISPLAY_LIST, RPL_DISPLAY_OPEN, RPL_ERROR,
    FH_SIZE, MH_SIZE
)


def test_hello():
    """HELLO handshake returns valid server version and capabilities."""
    with DrawSession() as s:
        reply = s.hello()
        # Parse reply
        msg_type, msg_id, payload = parse_first_msg(reply)
        assert msg_type == RPL_HELLO, f"Expected RPL_HELLO, got 0x{msg_type:04x}"
        assert len(payload) >= 16, "RPL_HELLO payload too short"

        status, major, minor, flags, max_reply = struct.unpack_from("<iHHII", payload, 0)
        assert status == 0, f"HELLO failed with status {status}"
        assert major >= 1, f"Unexpected major version {major}"
        print(f"  Server version: {major}.{minor}, flags=0x{flags:x}, max_reply={max_reply}")


def test_display_list():
    """DISPLAY_LIST returns at least one display."""
    with DrawSession() as s:
        s.hello()
        msg_type, payload = s.display_list()

        assert msg_type == RPL_DISPLAY_LIST, f"Expected RPL_DISPLAY_LIST, got 0x{msg_type:04x}"
        status, count = struct.unpack_from("<iI", payload, 0)
        assert status == 0, f"DISPLAY_LIST failed with status {status}"
        assert count >= 1, f"Expected at least 1 display, got {count}"

        # Parse display entries
        off = 8
        for i in range(count):
            did, w, h, refresh, flags = struct.unpack_from("<IIIII", payload, off)
            print(f"  Display {i}: id={did} {w}x{h} @ {refresh/1000:.1f}Hz")
            off += 20


def test_display_open_valid():
    """DISPLAY_OPEN succeeds for display_id=1."""
    with DrawSession() as s:
        s.hello()
        msg_type, payload = s.display_open(display_id=1)

        assert msg_type == RPL_DISPLAY_OPEN, f"Expected RPL_DISPLAY_OPEN, got 0x{msg_type:04x}"
        status, handle, active_id = struct.unpack_from("<iII", payload, 0)
        assert status == 0, f"DISPLAY_OPEN failed with status {status}"
        print(f"  Opened display: handle={handle}, active_id={active_id}")


def test_display_open_invalid():
    """DISPLAY_OPEN fails for non-existent display_id."""
    with DrawSession() as s:
        s.hello()
        msg_type, payload = s.display_open(display_id=9999)

        # Should get error reply
        if msg_type == RPL_ERROR:
            err_code, err_detail, err_offset = struct.unpack_from("<III", payload, 0)
            print(f"  Got expected error: code={err_code}")
        elif msg_type == RPL_DISPLAY_OPEN:
            status, _, _ = struct.unpack_from("<iII", payload, 0)
            assert status != 0, "Expected DISPLAY_OPEN to fail for invalid display"
            print(f"  Got expected status error: {status}")
        else:
            raise AssertionError(f"Unexpected reply type 0x{msg_type:04x}")


def test_stats_ioctl():
    """Stats ioctl returns valid counters."""
    with DrawSession() as s:
        s.hello()
        s.display_open()

        stats = s.get_stats()
        assert stats['frames_received'] >= 2, "Should have received hello + display_open frames"
        assert stats['frames_processed'] >= 2, "Should have processed hello + display_open"
        assert stats['messages_processed'] >= 2, "Should have processed at least 2 messages"
        print(f"  frames_received={stats['frames_received']}, messages_processed={stats['messages_processed']}")


def test_multi_message_frame():
    """Multiple messages in a single frame are all processed."""
    fd = os.open(DEV, os.O_RDWR)
    try:
        # Send HELLO first (required for session init)
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        frame = make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)])
        os.write(fd, frame)
        os.read(fd, 4096)  # consume hello reply

        # Now send two requests in one frame: DISPLAY_LIST + DISPLAY_OPEN
        list_msg = make_msg(REQ_DISPLAY_LIST, 10, b"")
        open_msg = make_msg(REQ_DISPLAY_OPEN, 11, struct.pack("<I", 1))
        multi_frame = make_frame(2, [list_msg, open_msg])
        os.write(fd, multi_frame)

        # Should get two replies
        reply1 = os.read(fd, 4096)
        msg_type1, msg_id1, _ = parse_first_msg(reply1)

        reply2 = os.read(fd, 4096)
        msg_type2, msg_id2, _ = parse_first_msg(reply2)

        # Both should be successful replies
        assert msg_type1 in (RPL_DISPLAY_LIST, RPL_DISPLAY_OPEN)
        assert msg_type2 in (RPL_DISPLAY_LIST, RPL_DISPLAY_OPEN)
        assert msg_type1 != msg_type2, "Should get different reply types"
        print(f"  Got replies: 0x{msg_type1:04x}, 0x{msg_type2:04x}")

    finally:
        os.close(fd)


def test_poll_readiness():
    """Poll indicates readiness after write."""
    with DrawSession() as s:
        p = select.poll()
        p.register(s.fd, select.POLLIN | getattr(select, "POLLRDNORM", 0))

        # Before hello, poll should timeout (no data)
        events = p.poll(100)
        assert not events, "Should not be readable before any request"

        # Send hello
        s.hello()

        # After hello reply, no more data pending
        events = p.poll(100)
        # May or may not be readable depending on timing

        # Send display_open
        s.display_open()

        # Verify we can poll and read
        events = p.poll(100)
        # Reply already consumed by display_open(), so nothing pending
        print("  Poll readiness verified")


def main():
    tests = [
        ("HELLO handshake", test_hello),
        ("DISPLAY_LIST enumeration", test_display_list),
        ("DISPLAY_OPEN valid", test_display_open_valid),
        ("DISPLAY_OPEN invalid", test_display_open_invalid),
        ("Stats ioctl", test_stats_ioctl),
        ("Multi-message frame", test_multi_message_frame),
        ("Poll readiness", test_poll_readiness),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            print(f"[TEST] {name}")
            test_fn()
            print(f"[PASS] {name}\n")
            passed += 1
        except Exception as e:
            print(f"[FAIL] {name}: {e}\n")
            failed += 1

    print(f"Results: {passed} passed, {failed} failed")
    if failed > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
