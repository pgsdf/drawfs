#!/usr/bin/env python3
"""
drawfs test helpers - common protocol encoding/decoding for all step tests.

This module provides:
- Protocol constants (magic, version, message types)
- Frame and message building functions
- Frame and message parsing functions
- Common operation helpers (hello, display_open, surface_create, etc.)
- ioctl helpers (stats, map_surface)
- Select-based read utilities
"""

import os
import struct
import select
import fcntl
from typing import Optional, Tuple, List, Dict, Any

# Device path
DEV = "/dev/draw"

# Protocol constants
DRAWFS_MAGIC = 0x31575244   # 'DRW1' little-endian
DRAWFS_VERSION = 0x0100     # 1.0

# Request types
REQ_HELLO          = 0x0001
REQ_DISPLAY_LIST   = 0x0010
REQ_DISPLAY_OPEN   = 0x0011
REQ_SURFACE_CREATE = 0x0020
REQ_SURFACE_DESTROY= 0x0021
REQ_SURFACE_PRESENT= 0x0022

# Reply types (request | 0x8000)
RPL_OK             = 0x8000
RPL_HELLO          = 0x8001
RPL_DISPLAY_LIST   = 0x8010
RPL_DISPLAY_OPEN   = 0x8011
RPL_SURFACE_CREATE = 0x8020
RPL_SURFACE_DESTROY= 0x8021
RPL_SURFACE_PRESENT= 0x8022
RPL_ERROR          = 0x8FFF

# Event types (0x9000+)
EVT_SURFACE_PRESENTED = 0x9002

# Pixel formats
FMT_XRGB8888 = 1

# Header format strings
FH_FMT = "<IHHII"   # frame header: magic, version, header_bytes, frame_bytes, frame_id
MH_FMT = "<HHIII"   # msg header: msg_type, msg_flags, msg_bytes, msg_id, reserved

FH_SIZE = struct.calcsize(FH_FMT)
MH_SIZE = struct.calcsize(MH_FMT)


def align4(n: int) -> int:
    """Align value to 4-byte boundary."""
    return (n + 3) & ~3


# =============================================================================
# Frame/Message Building
# =============================================================================

def make_msg(msg_type: int, msg_id: int, payload: bytes = b"") -> bytes:
    """Build a single message with header and payload."""
    payload = payload or b""
    msg_bytes = align4(MH_SIZE + len(payload))
    msg_hdr = struct.pack(MH_FMT, msg_type, 0, msg_bytes, msg_id, 0)
    msg = msg_hdr + payload
    msg += b"\x00" * (msg_bytes - len(msg))
    return msg


def make_frame(frame_id: int, msgs: List[bytes]) -> bytes:
    """Build a frame containing one or more messages."""
    body = b"".join(msgs)
    frame_bytes = align4(FH_SIZE + len(body))
    frame_hdr = struct.pack(
        FH_FMT,
        DRAWFS_MAGIC,
        DRAWFS_VERSION,
        FH_SIZE,
        frame_bytes,
        frame_id
    )
    frame = frame_hdr + body
    frame += b"\x00" * (frame_bytes - len(frame))
    return frame


# =============================================================================
# Frame/Message Parsing
# =============================================================================

def parse_frame_header(data: bytes) -> Tuple[int, int, int, int, int]:
    """Parse frame header, returns (magic, version, header_bytes, frame_bytes, frame_id)."""
    if len(data) < FH_SIZE:
        raise ValueError(f"Data too short for frame header: {len(data)} < {FH_SIZE}")
    return struct.unpack_from(FH_FMT, data, 0)


def parse_msg_header(data: bytes, offset: int = 0) -> Tuple[int, int, int, int, int]:
    """Parse message header at offset, returns (msg_type, msg_flags, msg_bytes, msg_id, reserved)."""
    if len(data) < offset + MH_SIZE:
        raise ValueError(f"Data too short for msg header at offset {offset}")
    return struct.unpack_from(MH_FMT, data, offset)


def parse_first_msg(frame: bytes) -> Tuple[int, int, bytes]:
    """Parse the first message from a frame, returns (msg_type, msg_id, payload)."""
    if len(frame) < FH_SIZE + MH_SIZE:
        raise ValueError(f"Frame too short: {len(frame)} bytes")

    msg_type, msg_flags, msg_bytes, msg_id, _ = parse_msg_header(frame, FH_SIZE)
    payload_off = FH_SIZE + MH_SIZE
    payload_len = msg_bytes - MH_SIZE
    payload = frame[payload_off:payload_off + payload_len]
    return msg_type, msg_id, payload


# =============================================================================
# Read Utilities
# =============================================================================

def read_frame(fd: int, timeout_ms: int = 2000) -> bytes:
    """Read one frame from fd, using select to avoid indefinite blocking."""
    deadline_s = timeout_ms / 1000.0
    readable, _, _ = select.select([fd], [], [], deadline_s)
    if fd not in readable:
        raise TimeoutError(f"Timeout waiting for frame ({timeout_ms}ms)")
    return os.read(fd, 4096)


def read_msg(fd: int, timeout_ms: int = 2000) -> Tuple[int, int, bytes]:
    """Read one frame and parse the first message, returns (msg_type, msg_id, payload)."""
    frame = read_frame(fd, timeout_ms)
    return parse_first_msg(frame)


def drain_until(fd: int, msg_type: int, timeout_ms: int = 2000, max_msgs: int = 20) -> Tuple[int, bytes]:
    """
    Read messages until we find one with the given msg_type.
    Returns (msg_id, payload) of the matching message.
    Raises if not found within max_msgs reads.
    """
    for _ in range(max_msgs):
        mt, mid, payload = read_msg(fd, timeout_ms)
        if mt == msg_type:
            return mid, payload
    raise RuntimeError(f"Did not find msg_type 0x{msg_type:04x} within {max_msgs} messages")


def drain_all(fd: int, max_msgs: int = 500, timeout_s: float = 5.0) -> int:
    """
    Drain all available messages from fd using select.
    Returns count of messages drained.
    """
    import time
    drained = 0
    start = time.time()
    while drained < max_msgs and (time.time() - start) < timeout_s:
        readable, _, _ = select.select([fd], [], [], 0.1)
        if fd not in readable:
            break
        data = os.read(fd, 4096)
        if not data:
            break
        drained += 1
    return drained


# =============================================================================
# Common Protocol Operations
# =============================================================================

def send(fd: int, frame: bytes) -> None:
    """Write a frame to fd."""
    os.write(fd, frame)


def hello(fd: int, frame_id: int = 1, msg_id: int = 1) -> bytes:
    """Send HELLO and read reply. Returns reply payload."""
    payload = struct.pack("<HHII", 1, 0, 0, 65536)  # client_major, minor, flags, max_reply
    send(fd, make_frame(frame_id, [make_msg(REQ_HELLO, msg_id, payload)]))
    return read_frame(fd)


def display_list(fd: int, frame_id: int = 2, msg_id: int = 2) -> Tuple[int, bytes]:
    """Send DISPLAY_LIST and read reply. Returns (msg_type, payload)."""
    send(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_LIST, msg_id, b"")]))
    mt, mid, payload = read_msg(fd)
    return mt, payload


def display_open(fd: int, display_id: int = 1, frame_id: int = 3, msg_id: int = 3) -> Tuple[int, bytes]:
    """Send DISPLAY_OPEN and read reply. Returns (msg_type, payload)."""
    payload = struct.pack("<I", display_id)
    send(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_OPEN, msg_id, payload)]))
    mt, mid, payload = read_msg(fd)
    return mt, payload


def surface_create(
    fd: int,
    width: int,
    height: int,
    fmt: int = FMT_XRGB8888,
    flags: int = 0,
    frame_id: int = 4,
    msg_id: int = 4,
    skip_events: bool = False
) -> Tuple[int, int, int, int]:
    """
    Send SURFACE_CREATE and read reply.
    Returns (status, surface_id, stride, total_bytes).
    If skip_events=True, uses drain_until to skip any pending events.
    """
    payload = struct.pack("<IIII", width, height, fmt, flags)
    send(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_CREATE, msg_id, payload)]))
    if skip_events:
        _, reply_payload = drain_until(fd, RPL_SURFACE_CREATE)
    else:
        mt, mid, reply_payload = read_msg(fd)
        if mt == RPL_ERROR:
            # Parse error: err_code, err_detail, err_offset
            err_code, _, _ = struct.unpack_from("<III", reply_payload, 0)
            return err_code, 0, 0, 0
        if mt != RPL_SURFACE_CREATE:
            raise RuntimeError(f"Expected SURFACE_CREATE reply, got 0x{mt:04x}")
    status, sid, stride, total = struct.unpack_from("<iIII", reply_payload, 0)
    return status, sid, stride, total


def surface_destroy(
    fd: int,
    surface_id: int,
    frame_id: int = 5,
    msg_id: int = 5,
    skip_events: bool = False
) -> int:
    """
    Send SURFACE_DESTROY and read reply.
    Returns status.
    If skip_events=True, uses drain_until to skip any pending events.
    """
    payload = struct.pack("<I", surface_id)
    send(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_DESTROY, msg_id, payload)]))
    if skip_events:
        _, reply_payload = drain_until(fd, RPL_SURFACE_DESTROY)
    else:
        mt, mid, reply_payload = read_msg(fd)
        if mt == RPL_ERROR:
            err_code, _, _ = struct.unpack_from("<III", reply_payload, 0)
            return err_code
        if mt != RPL_SURFACE_DESTROY:
            raise RuntimeError(f"Expected SURFACE_DESTROY reply, got 0x{mt:04x}")
    status, = struct.unpack_from("<i", reply_payload, 0)
    return status


def surface_present(
    fd: int,
    surface_id: int,
    cookie: int = 0,
    frame_id: int = 6,
    msg_id: int = 6,
    skip_events: bool = False
) -> Tuple[int, int, int]:
    """
    Send SURFACE_PRESENT and read reply (not event).
    Returns (status, surface_id, cookie) from reply.
    If skip_events=True, uses drain_until to skip any pending events.
    """
    payload = struct.pack("<IIQ", surface_id, 0, cookie)
    send(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_PRESENT, msg_id, payload)]))
    if skip_events:
        _, reply_payload = drain_until(fd, RPL_SURFACE_PRESENT)
    else:
        mt, mid, reply_payload = read_msg(fd)
        if mt == RPL_ERROR:
            err_code, _, _ = struct.unpack_from("<III", reply_payload, 0)
            return err_code, surface_id, cookie
        if mt != RPL_SURFACE_PRESENT:
            raise RuntimeError(f"Expected SURFACE_PRESENT reply, got 0x{mt:04x}")
    status, sid, cookie_out = struct.unpack_from("<iIQ", reply_payload, 0)
    return status, sid, cookie_out


def read_presented_event(fd: int, timeout_ms: int = 2000) -> Tuple[int, int, int]:
    """
    Read SURFACE_PRESENTED event.
    Returns (surface_id, reserved, cookie).
    """
    mt, mid, payload = read_msg(fd, timeout_ms)
    if mt != EVT_SURFACE_PRESENTED:
        raise RuntimeError(f"Expected SURFACE_PRESENTED event, got 0x{mt:04x}")
    sid, reserved, cookie = struct.unpack_from("<IIQ", payload, 0)
    return sid, reserved, cookie


# =============================================================================
# ioctl Helpers
# =============================================================================

def _ioc(inout: int, group: int, num: int, size: int) -> int:
    """Compute FreeBSD ioctl number."""
    IOCPARM_MASK = 0x1fff
    return inout | ((size & IOCPARM_MASK) << 16) | ((group & 0xff) << 8) | (num & 0xff)


def _ior(group: str, num: int, size: int) -> int:
    """_IOR macro: read ioctl."""
    return _ioc(0x40000000, ord(group), num, size)


def _iowr(group: str, num: int, size: int) -> int:
    """_IOWR macro: read/write ioctl."""
    return _ioc(0xC0000000, ord(group), num, size)


# Stats ioctl: _IOR('D', 0x01, struct drawfs_stats) - 96 bytes
STATS_SIZE = 96  # 9 uint64s + 4 uint32s + 1 uint64
DRAWFSGIOC_STATS = _ior('D', 0x01, STATS_SIZE)

def get_stats(fd: int) -> Dict[str, int]:
    """
    Get session statistics via ioctl.
    Returns dict with: frames_received, frames_processed, frames_invalid,
    messages_processed, messages_unsupported, events_enqueued, events_dropped,
    bytes_in, bytes_out, evq_depth, inbuf_bytes, evq_bytes, surfaces_count,
    surfaces_bytes.
    """
    buf = bytearray(STATS_SIZE)
    fcntl.ioctl(fd, DRAWFSGIOC_STATS, buf)
    vals = struct.unpack("<QQQQQQQQQIIIIQ", buf)
    return {
        'frames_received': vals[0],
        'frames_processed': vals[1],
        'frames_invalid': vals[2],
        'messages_processed': vals[3],
        'messages_unsupported': vals[4],
        'events_enqueued': vals[5],
        'events_dropped': vals[6],
        'bytes_in': vals[7],
        'bytes_out': vals[8],
        'evq_depth': vals[9],
        'inbuf_bytes': vals[10],
        'evq_bytes': vals[11],
        'surfaces_count': vals[12],
        'surfaces_bytes': vals[13],
    }


# Map surface ioctl: _IOWR('D', 0x02, struct drawfs_map_surface) - 16 bytes
MAP_SURFACE_SIZE = 16  # int32 status, uint32 surface_id, uint32 stride, uint32 total
DRAWFSGIOC_MAP_SURFACE = _iowr('D', 0x02, MAP_SURFACE_SIZE)

def map_surface(fd: int, surface_id: int) -> Tuple[int, int, int, int]:
    """
    Select a surface for mmap via ioctl.
    Returns (status, surface_id, stride, total_bytes).
    """
    buf = bytearray(MAP_SURFACE_SIZE)
    struct.pack_into("<iI", buf, 0, 0, surface_id)
    fcntl.ioctl(fd, DRAWFSGIOC_MAP_SURFACE, buf, True)
    status, sid, stride, total = struct.unpack_from("<iIII", buf, 0)
    return status, sid, stride, total


# =============================================================================
# Session Context Manager
# =============================================================================

class DrawSession:
    """
    Context manager for a drawfs session.

    Usage:
        with DrawSession() as s:
            s.hello()
            s.display_open()
            status, sid, stride, total = s.surface_create(256, 256)
    """

    def __init__(self, dev: str = DEV):
        self.dev = dev
        self.fd: Optional[int] = None
        self._frame_id = 0
        self._msg_id = 0

    def __enter__(self) -> 'DrawSession':
        self.fd = os.open(self.dev, os.O_RDWR)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        return False

    def _next_ids(self) -> Tuple[int, int]:
        self._frame_id += 1
        self._msg_id += 1
        return self._frame_id, self._msg_id

    def send(self, frame: bytes) -> None:
        send(self.fd, frame)

    def read_frame(self, timeout_ms: int = 2000) -> bytes:
        return read_frame(self.fd, timeout_ms)

    def read_msg(self, timeout_ms: int = 2000) -> Tuple[int, int, bytes]:
        return read_msg(self.fd, timeout_ms)

    def hello(self) -> bytes:
        fid, mid = self._next_ids()
        return hello(self.fd, fid, mid)

    def display_list(self) -> Tuple[int, bytes]:
        fid, mid = self._next_ids()
        return display_list(self.fd, fid, mid)

    def display_open(self, display_id: int = 1) -> Tuple[int, bytes]:
        fid, mid = self._next_ids()
        return display_open(self.fd, display_id, fid, mid)

    def surface_create(self, width: int, height: int, fmt: int = FMT_XRGB8888, skip_events: bool = False) -> Tuple[int, int, int, int]:
        fid, mid = self._next_ids()
        return surface_create(self.fd, width, height, fmt, 0, fid, mid, skip_events)

    def surface_destroy(self, surface_id: int, skip_events: bool = False) -> int:
        fid, mid = self._next_ids()
        return surface_destroy(self.fd, surface_id, fid, mid, skip_events)

    def surface_present(self, surface_id: int, cookie: int = 0, skip_events: bool = False) -> Tuple[int, int, int]:
        fid, mid = self._next_ids()
        return surface_present(self.fd, surface_id, cookie, fid, mid, skip_events)

    def read_presented_event(self, timeout_ms: int = 2000) -> Tuple[int, int, int]:
        return read_presented_event(self.fd, timeout_ms)

    def get_stats(self) -> Dict[str, int]:
        return get_stats(self.fd)

    def map_surface(self, surface_id: int) -> Tuple[int, int, int, int]:
        return map_surface(self.fd, surface_id)

    def drain_all(self, max_msgs: int = 500, timeout_s: float = 5.0) -> int:
        return drain_all(self.fd, max_msgs, timeout_s)
