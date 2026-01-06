#!/usr/bin/env python3
"""
test_diagnostic.py - Simple diagnostic to check basic device communication

Run this first to verify the drawfs device is responding properly.
"""

import os
import struct
import select
from drawfs_test import (
    DEV, make_frame, make_msg, parse_first_msg,
    REQ_HELLO, REQ_DISPLAY_LIST, REQ_DISPLAY_OPEN, REQ_SURFACE_CREATE,
    RPL_HELLO, RPL_DISPLAY_LIST, RPL_DISPLAY_OPEN, RPL_SURFACE_CREATE, RPL_ERROR,
    FH_SIZE, MH_SIZE, FMT_XRGB8888
)


def main():
    print("Drawfs Device Diagnostic")
    print("=" * 40)

    # Check device exists
    if not os.path.exists(DEV):
        print(f"FAIL: Device {DEV} does not exist")
        return 1

    print(f"[OK] Device {DEV} exists")

    # Open device
    try:
        fd = os.open(DEV, os.O_RDWR)
        print(f"[OK] Opened device (fd={fd})")
    except OSError as e:
        print(f"FAIL: Cannot open device: {e}")
        return 1

    try:
        # Build HELLO request
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        frame = make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)])
        print(f"[OK] Built HELLO frame ({len(frame)} bytes)")
        print(f"     Frame hex: {frame[:40].hex()}...")

        # Write HELLO
        written = os.write(fd, frame)
        print(f"[OK] Wrote {written} bytes")

        # Wait for response with poll
        p = select.poll()
        p.register(fd, select.POLLIN | select.POLLRDNORM)
        print("     Waiting for response (5 sec timeout)...")

        events = p.poll(5000)
        if not events:
            print("FAIL: Timeout waiting for response")
            print("      The kernel module may not be processing requests")
            return 1

        print(f"[OK] Poll returned events: {events}")

        # Read response
        response = os.read(fd, 4096)
        print(f"[OK] Read {len(response)} bytes")
        print(f"     Response hex: {response[:40].hex()}...")

        # Parse response
        if len(response) < FH_SIZE + MH_SIZE:
            print(f"FAIL: Response too short ({len(response)} bytes)")
            return 1

        msg_type, msg_id, payload = parse_first_msg(response)
        print(f"[OK] Parsed response: msg_type=0x{msg_type:04x}, msg_id={msg_id}")

        if msg_type == RPL_HELLO:
            # Payload can be 12 bytes (without max_reply) or 16 bytes (with max_reply)
            if len(payload) >= 12:
                status, major, minor, flags = struct.unpack_from("<iHHI", payload, 0)
                max_reply = 0
                if len(payload) >= 16:
                    max_reply, = struct.unpack_from("<I", payload, 12)
                print(f"[OK] RPL_HELLO received!")
                print(f"     status={status}")
                print(f"     server_version={major}.{minor}")
                print(f"     flags=0x{flags:08x}")
                if len(payload) >= 16:
                    print(f"     max_reply_bytes={max_reply}")
                else:
                    print(f"     (payload={len(payload)} bytes, no max_reply field)")
                if status != 0:
                    print(f"\nFAIL: HELLO returned non-zero status: {status}")
                    return 1
            else:
                print(f"FAIL: RPL_HELLO payload too short ({len(payload)} bytes)")
                return 1

        # Step 2: DISPLAY_LIST
        print("\n--- Testing DISPLAY_LIST ---")
        list_frame = make_frame(2, [make_msg(REQ_DISPLAY_LIST, 2, b"")])
        os.write(fd, list_frame)

        events = p.poll(5000)
        if not events:
            print("FAIL: Timeout waiting for DISPLAY_LIST response")
            return 1

        response = os.read(fd, 4096)
        msg_type, msg_id, payload = parse_first_msg(response)
        print(f"[OK] Response: msg_type=0x{msg_type:04x}")

        if msg_type == RPL_ERROR:
            err_code, _, _ = struct.unpack_from("<III", payload, 0)
            print(f"FAIL: DISPLAY_LIST got RPL_ERROR code={err_code}")
            return 1

        if msg_type == RPL_DISPLAY_LIST:
            status, count = struct.unpack_from("<iI", payload, 0)
            print(f"[OK] RPL_DISPLAY_LIST: status={status}, count={count}")
        else:
            print(f"FAIL: Expected RPL_DISPLAY_LIST (0x8010), got 0x{msg_type:04x}")
            return 1

        # Step 3: DISPLAY_OPEN
        print("\n--- Testing DISPLAY_OPEN ---")
        open_payload = struct.pack("<I", 1)  # display_id=1
        open_frame = make_frame(3, [make_msg(REQ_DISPLAY_OPEN, 3, open_payload)])
        os.write(fd, open_frame)

        events = p.poll(5000)
        if not events:
            print("FAIL: Timeout waiting for DISPLAY_OPEN response")
            return 1

        response = os.read(fd, 4096)
        msg_type, msg_id, payload = parse_first_msg(response)
        print(f"[OK] Response: msg_type=0x{msg_type:04x}")

        if msg_type == RPL_ERROR:
            err_code, _, _ = struct.unpack_from("<III", payload, 0)
            print(f"FAIL: DISPLAY_OPEN got RPL_ERROR code={err_code}")
            return 1

        if msg_type == RPL_DISPLAY_OPEN:
            status, handle, active_id = struct.unpack_from("<iII", payload, 0)
            print(f"[OK] RPL_DISPLAY_OPEN: status={status}, handle={handle}, active_id={active_id}")
            if status != 0:
                print(f"FAIL: DISPLAY_OPEN returned status {status}")
                return 1
        else:
            print(f"FAIL: Expected RPL_DISPLAY_OPEN (0x8011), got 0x{msg_type:04x}")
            return 1

        # Step 4: SURFACE_CREATE
        print("\n--- Testing SURFACE_CREATE ---")
        create_payload = struct.pack("<IIII", 64, 64, FMT_XRGB8888, 0)
        create_frame = make_frame(4, [make_msg(REQ_SURFACE_CREATE, 4, create_payload)])
        os.write(fd, create_frame)

        events = p.poll(5000)
        if not events:
            print("FAIL: Timeout waiting for SURFACE_CREATE response")
            return 1

        response = os.read(fd, 4096)
        msg_type, msg_id, payload = parse_first_msg(response)
        print(f"[OK] Response: msg_type=0x{msg_type:04x}")

        if msg_type == RPL_ERROR:
            err_code, err_detail, err_offset = struct.unpack_from("<III", payload, 0)
            print(f"FAIL: SURFACE_CREATE got RPL_ERROR")
            print(f"      err_code={err_code}")
            print(f"      err_detail={err_detail}")
            print(f"      err_offset={err_offset}")
            return 1

        if msg_type == RPL_SURFACE_CREATE:
            status, sid, stride, total = struct.unpack_from("<iIII", payload, 0)
            print(f"[OK] RPL_SURFACE_CREATE: status={status}, surface_id={sid}, stride={stride}, total={total}")
            if status != 0:
                print(f"FAIL: SURFACE_CREATE returned status {status}")
                return 1
        else:
            print(f"FAIL: Expected RPL_SURFACE_CREATE (0x8020), got 0x{msg_type:04x}")
            return 1

        print("\n" + "=" * 40)
        print("SUCCESS: All protocol operations working!")
        return 0

    finally:
        os.close(fd)
        print(f"[OK] Closed device")


if __name__ == "__main__":
    exit(main())
