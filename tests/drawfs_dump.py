#!/usr/bin/env python3
"""
drawfs_dump.py - Debug tool to dump decoded frames from raw read buffer.

Usage:
    # Dump hex-encoded frame from command line
    ./drawfs_dump.py 44525731000110002c00000001000000...

    # Dump binary frame from stdin
    cat frame.bin | ./drawfs_dump.py

    # Dump hex from stdin
    echo "44525731..." | ./drawfs_dump.py --hex

    # Live dump from device (requires root)
    sudo ./drawfs_dump.py --live

This tool decodes drawfs protocol frames and displays:
- Frame header (magic, version, size, frame_id)
- Each message header (type, flags, size, msg_id)
- Decoded payload for known message types
"""

import sys
import struct
import os
import select
from typing import Optional, Tuple, List

# Protocol constants
DRAWFS_MAGIC = 0x31575244   # 'DRW1' little-endian
DRAWFS_VERSION = 0x0100     # 1.0

# Message type names
MSG_TYPES = {
    0x0001: "REQ_HELLO",
    0x0010: "REQ_DISPLAY_LIST",
    0x0011: "REQ_DISPLAY_OPEN",
    0x0020: "REQ_SURFACE_CREATE",
    0x0021: "REQ_SURFACE_DESTROY",
    0x0022: "REQ_SURFACE_PRESENT",
    0x8000: "RPL_OK",
    0x8001: "RPL_HELLO",
    0x8010: "RPL_DISPLAY_LIST",
    0x8011: "RPL_DISPLAY_OPEN",
    0x8020: "RPL_SURFACE_CREATE",
    0x8021: "RPL_SURFACE_DESTROY",
    0x8022: "RPL_SURFACE_PRESENT",
    0x8FFF: "RPL_ERROR",
    0x9002: "EVT_SURFACE_PRESENTED",
}

# Error codes (from drawfs_proto.h enum drawfs_err_code)
ERROR_CODES = {
    0: "OK",
    1: "INVALID_FRAME",
    2: "INVALID_MSG",
    3: "UNSUPPORTED_VERSION",
    4: "UNSUPPORTED_CAP",
    5: "PERMISSION",
    6: "NOT_FOUND",
    7: "BUSY",
    8: "NO_MEMORY",
    9: "INVALID_HANDLE",
    10: "INVALID_STATE",
    11: "INVALID_ARG",
    12: "OVERFLOW",
    13: "IO",
    14: "INTERNAL",
}

# Pixel formats
PIXEL_FORMATS = {
    1: "XRGB8888",
}

# Header sizes
FH_SIZE = 20  # Frame header
MH_SIZE = 16  # Message header


def hex_dump(data: bytes, prefix: str = "    ") -> str:
    """Format bytes as hex dump with ASCII."""
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{prefix}{i:04x}: {hex_part:<48} {ascii_part}")
    return "\n".join(lines) if lines else f"{prefix}(empty)"


def decode_frame_header(data: bytes) -> Tuple[int, int, int, int, int]:
    """Decode frame header: magic, version, header_bytes, frame_bytes, frame_id."""
    if len(data) < FH_SIZE:
        raise ValueError(f"Data too short for frame header: {len(data)} < {FH_SIZE}")
    return struct.unpack_from("<IHHII", data, 0)


def decode_msg_header(data: bytes, offset: int) -> Tuple[int, int, int, int, int]:
    """Decode message header: msg_type, msg_flags, msg_bytes, msg_id, reserved."""
    if len(data) < offset + MH_SIZE:
        raise ValueError(f"Data too short for msg header at offset {offset}")
    return struct.unpack_from("<HHIII", data, offset)


def decode_payload(msg_type: int, payload: bytes) -> List[str]:
    """Decode known payload types and return description lines."""
    lines = []

    try:
        if msg_type == 0x0001:  # REQ_HELLO
            if len(payload) >= 12:
                major, minor, flags, max_reply = struct.unpack_from("<HHII", payload, 0)
                lines.append(f"client_version: {major}.{minor}")
                lines.append(f"flags: 0x{flags:08x}")
                lines.append(f"max_reply_bytes: {max_reply}")

        elif msg_type == 0x8001:  # RPL_HELLO
            if len(payload) >= 16:
                status, major, minor, flags, max_reply_bytes = struct.unpack_from("<iHHII", payload, 0)
                lines.append(f"status: {status} ({os.strerror(status) if status else 'OK'})")
                lines.append(f"server_version: {major}.{minor}")
                lines.append(f"flags: 0x{flags:08x}")
                lines.append(f"max_reply_bytes: {max_reply_bytes}")

        elif msg_type == 0x0011:  # REQ_DISPLAY_OPEN
            if len(payload) >= 4:
                display_id, = struct.unpack_from("<I", payload, 0)
                lines.append(f"display_id: {display_id}")

        elif msg_type == 0x8010:  # RPL_DISPLAY_LIST
            if len(payload) >= 8:
                status, count = struct.unpack_from("<iI", payload, 0)
                lines.append(f"status: {status} ({os.strerror(status) if status else 'OK'})")
                lines.append(f"display_count: {count}")
                off = 8
                for i in range(count):
                    if off + 20 <= len(payload):
                        did, w, h, refresh, flags = struct.unpack_from("<IIIII", payload, off)
                        lines.append(f"  display[{i}]: id={did} {w}x{h} @ {refresh/1000:.1f}Hz flags=0x{flags:x}")
                        off += 20

        elif msg_type == 0x8011:  # RPL_DISPLAY_OPEN
            if len(payload) >= 12:
                status, handle, active_id = struct.unpack_from("<iII", payload, 0)
                lines.append(f"status: {status} ({os.strerror(status) if status else 'OK'})")
                lines.append(f"display_handle: {handle}")
                lines.append(f"active_display_id: {active_id}")

        elif msg_type == 0x0020:  # REQ_SURFACE_CREATE
            if len(payload) >= 16:
                w, h, fmt, flags = struct.unpack_from("<IIII", payload, 0)
                fmt_name = PIXEL_FORMATS.get(fmt, f"unknown({fmt})")
                lines.append(f"size: {w}x{h}")
                lines.append(f"format: {fmt_name}")
                lines.append(f"flags: 0x{flags:08x}")

        elif msg_type == 0x8020:  # RPL_SURFACE_CREATE
            if len(payload) >= 16:
                status, sid, stride, total = struct.unpack_from("<iIII", payload, 0)
                lines.append(f"status: {status} ({os.strerror(status) if status else 'OK'})")
                lines.append(f"surface_id: {sid}")
                lines.append(f"stride_bytes: {stride}")
                lines.append(f"bytes_total: {total}")

        elif msg_type == 0x0021:  # REQ_SURFACE_DESTROY
            if len(payload) >= 4:
                sid, = struct.unpack_from("<I", payload, 0)
                lines.append(f"surface_id: {sid}")

        elif msg_type == 0x8021:  # RPL_SURFACE_DESTROY
            if len(payload) >= 8:
                status, sid = struct.unpack_from("<iI", payload, 0)
                lines.append(f"status: {status} ({os.strerror(status) if status else 'OK'})")
                lines.append(f"surface_id: {sid}")

        elif msg_type == 0x0022:  # REQ_SURFACE_PRESENT
            if len(payload) >= 16:
                sid, reserved, cookie = struct.unpack_from("<IIQ", payload, 0)
                lines.append(f"surface_id: {sid}")
                lines.append(f"cookie: 0x{cookie:016x}")

        elif msg_type == 0x8022:  # RPL_SURFACE_PRESENT
            if len(payload) >= 16:
                status, sid, cookie = struct.unpack_from("<iIQ", payload, 0)
                lines.append(f"status: {status} ({os.strerror(status) if status else 'OK'})")
                lines.append(f"surface_id: {sid}")
                lines.append(f"cookie: 0x{cookie:016x}")

        elif msg_type == 0x9002:  # EVT_SURFACE_PRESENTED
            if len(payload) >= 16:
                sid, reserved, cookie = struct.unpack_from("<IIQ", payload, 0)
                lines.append(f"surface_id: {sid}")
                lines.append(f"cookie: 0x{cookie:016x}")

        elif msg_type == 0x8FFF:  # RPL_ERROR
            if len(payload) >= 12:
                err_code, err_detail, err_offset = struct.unpack_from("<III", payload, 0)
                err_name = ERROR_CODES.get(err_code, f"unknown({err_code})")
                lines.append(f"err_code: {err_code} ({err_name})")
                lines.append(f"err_detail: {err_detail}")
                lines.append(f"err_offset: {err_offset}")

    except struct.error as e:
        lines.append(f"(decode error: {e})")

    return lines


def dump_frame(data: bytes, frame_num: int = 1) -> None:
    """Dump a single frame with all messages."""
    print(f"=== Frame {frame_num} ({len(data)} bytes) ===")
    print()

    if len(data) < FH_SIZE:
        print(f"ERROR: Data too short for frame header ({len(data)} < {FH_SIZE})")
        print(hex_dump(data))
        return

    magic, version, hdr_bytes, frame_bytes, frame_id = decode_frame_header(data)

    magic_ok = "OK" if magic == DRAWFS_MAGIC else "INVALID"
    magic_str = struct.pack("<I", magic).decode('ascii', errors='replace')

    print(f"Frame Header:")
    print(f"  magic:        0x{magic:08x} ('{magic_str}') [{magic_ok}]")
    print(f"  version:      0x{version:04x} ({version >> 8}.{version & 0xff})")
    print(f"  header_bytes: {hdr_bytes}")
    print(f"  frame_bytes:  {frame_bytes}")
    print(f"  frame_id:     {frame_id}")
    print()

    if magic != DRAWFS_MAGIC:
        print("ERROR: Invalid magic - cannot parse messages")
        print(hex_dump(data))
        return

    if frame_bytes > len(data):
        print(f"WARNING: frame_bytes ({frame_bytes}) > data length ({len(data)})")
        frame_bytes = len(data)

    # Parse messages
    pos = hdr_bytes
    msg_num = 0
    while pos + MH_SIZE <= frame_bytes:
        msg_num += 1
        msg_type, msg_flags, msg_bytes, msg_id, reserved = decode_msg_header(data, pos)

        type_name = MSG_TYPES.get(msg_type, "UNKNOWN")

        print(f"Message {msg_num}:")
        print(f"  offset:     {pos}")
        print(f"  msg_type:   0x{msg_type:04x} ({type_name})")
        print(f"  msg_flags:  0x{msg_flags:04x}")
        print(f"  msg_bytes:  {msg_bytes}")
        print(f"  msg_id:     {msg_id}")

        if msg_bytes < MH_SIZE:
            print(f"  ERROR: msg_bytes < header size")
            break

        payload_start = pos + MH_SIZE
        payload_len = msg_bytes - MH_SIZE
        payload_end = min(pos + msg_bytes, frame_bytes)
        payload = data[payload_start:payload_end]

        if payload_len > 0:
            print(f"  payload ({len(payload)} bytes):")
            decoded = decode_payload(msg_type, payload)
            if decoded:
                for line in decoded:
                    print(f"    {line}")
            else:
                print(hex_dump(payload, "    "))
        print()

        # Advance to next message (4-byte aligned)
        pos = ((pos + msg_bytes) + 3) & ~3
        if pos <= pos - msg_bytes:  # Overflow check
            break

    if msg_num == 0:
        print("No messages found in frame")


def parse_hex(hex_str: str) -> bytes:
    """Parse hex string (with or without spaces) to bytes."""
    # Remove whitespace and common prefixes
    hex_str = hex_str.strip().replace(" ", "").replace("\n", "")
    if hex_str.startswith("0x"):
        hex_str = hex_str[2:]
    return bytes.fromhex(hex_str)


def read_live_frame(fd: int, timeout_s: float = 5.0) -> Optional[bytes]:
    """Read a frame from the device with timeout."""
    readable, _, _ = select.select([fd], [], [], timeout_s)
    if fd not in readable:
        return None
    return os.read(fd, 4096)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Dump decoded drawfs protocol frames",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dump hex from command line
  %(prog)s 44525731000110002c00000001000000018000001c00000065...

  # Dump binary from stdin
  cat frame.bin | %(prog)s

  # Dump hex from stdin
  echo "44525731..." | %(prog)s --hex

  # Live capture from device
  sudo %(prog)s --live --count 5
"""
    )
    parser.add_argument("hexdata", nargs="?", help="Hex-encoded frame data")
    parser.add_argument("--hex", action="store_true",
                        help="Treat stdin as hex (not binary)")
    parser.add_argument("--live", action="store_true",
                        help="Read live frames from /dev/draw")
    parser.add_argument("--device", default="/dev/draw",
                        help="Device path for --live mode")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of frames to read in --live mode")
    parser.add_argument("--timeout", type=float, default=5.0,
                        help="Timeout in seconds for --live mode")

    args = parser.parse_args()

    if args.live:
        # Live mode: read from device
        try:
            fd = os.open(args.device, os.O_RDWR)
        except OSError as e:
            print(f"Cannot open {args.device}: {e}", file=sys.stderr)
            print("Live mode requires root privileges.", file=sys.stderr)
            sys.exit(1)

        try:
            print(f"Reading from {args.device}...")
            print(f"(waiting for frames, timeout={args.timeout}s)")
            print()
            for i in range(args.count):
                data = read_live_frame(fd, args.timeout)
                if data is None:
                    print(f"Timeout waiting for frame {i+1}")
                    break
                dump_frame(data, i + 1)
        finally:
            os.close(fd)

    elif args.hexdata:
        # Hex data from command line
        try:
            data = parse_hex(args.hexdata)
            dump_frame(data)
        except ValueError as e:
            print(f"Invalid hex data: {e}", file=sys.stderr)
            sys.exit(1)

    elif not sys.stdin.isatty():
        # Read from stdin
        if args.hex:
            hex_str = sys.stdin.read()
            try:
                data = parse_hex(hex_str)
            except ValueError as e:
                print(f"Invalid hex data: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            data = sys.stdin.buffer.read()

        if not data:
            print("No data received", file=sys.stderr)
            sys.exit(1)

        dump_frame(data)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
