#!/usr/bin/env python3
"""Step 17: Multi session interleaved present test.

Two independent sessions (two fds) must not leak state:
- surface ids are per session
- MAP_SURFACE selection is per session
- events must be delivered only to the fd that generated them
"""

import mmap
import os
import select
import struct
from drawfs_test import (
    DEV, make_frame, make_msg, parse_first_msg, map_surface,
    REQ_HELLO, REQ_DISPLAY_OPEN, REQ_SURFACE_CREATE, REQ_SURFACE_PRESENT,
    RPL_DISPLAY_OPEN, RPL_SURFACE_CREATE, RPL_SURFACE_PRESENT,
    EVT_SURFACE_PRESENTED, FMT_XRGB8888
)


def read_one(fd):
    buf = os.read(fd, 4096)
    return parse_first_msg(buf)


def hello(fd, frame_id: int, msg_id: int):
    hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_HELLO, msg_id, hello_payload)]))
    _ = os.read(fd, 4096)


def display_open(fd, frame_id: int, msg_id: int, display_id: int = 1):
    open_payload = struct.pack("<I", display_id)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_DISPLAY_OPEN, msg_id, open_payload)]))
    msg_type, _mid, payload = read_one(fd)
    if msg_type != RPL_DISPLAY_OPEN:
        raise RuntimeError(f"expected DISPLAY_OPEN reply, got 0x{msg_type:x}")
    status, handle, active_id = struct.unpack_from("<iII", payload, 0)
    if status != 0:
        raise RuntimeError(f"DISPLAY_OPEN status={status}")
    return handle


def surface_create_raw(fd, frame_id: int, msg_id: int, w: int, h: int, fmt: int = 1):
    sc_req = struct.pack("<IIII", w, h, fmt, 0)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_CREATE, msg_id, sc_req)]))
    msg_type, _mid, payload = read_one(fd)
    if msg_type != RPL_SURFACE_CREATE:
        raise RuntimeError(f"expected SURFACE_CREATE reply, got 0x{msg_type:x}")
    status, sid, stride, total = struct.unpack_from("<iIII", payload, 0)
    if status != 0:
        raise RuntimeError(f"SURFACE_CREATE status={status}")
    return sid, stride, total


def surface_present_raw(fd, frame_id: int, msg_id: int, surface_id: int, cookie: int):
    req = struct.pack("<IIQ", surface_id, 0, cookie)
    os.write(fd, make_frame(frame_id, [make_msg(REQ_SURFACE_PRESENT, msg_id, req)]))
    msg_type, _mid, payload = read_one(fd)
    if msg_type != RPL_SURFACE_PRESENT:
        raise RuntimeError(f"expected SURFACE_PRESENT reply, got 0x{msg_type:x}")
    status, = struct.unpack_from("<i", payload, 0)
    if status != 0:
        raise RuntimeError(f"SURFACE_PRESENT status={status}")


def wait_presented(fd, timeout_ms: int = 1000):
    p = select.poll()
    p.register(fd, select.POLLIN | select.POLLRDNORM)
    ev = p.poll(timeout_ms)
    if not ev:
        raise RuntimeError("timeout waiting for event")
    msg_type, _mid, payload = read_one(fd)
    if msg_type != EVT_SURFACE_PRESENTED:
        raise RuntimeError(f"expected SURFACE_PRESENTED (0x9002), got 0x{msg_type:x}")
    surface_id, flags, cookie = struct.unpack_from("<IIQ", payload, 0)
    return surface_id, flags, cookie


def main():
    fd1 = os.open(DEV, os.O_RDWR)
    fd2 = os.open(DEV, os.O_RDWR)
    try:
        # Session 1 init
        hello(fd1, frame_id=1, msg_id=1)
        display_open(fd1, frame_id=2, msg_id=2, display_id=1)

        # Session 2 init
        hello(fd2, frame_id=10, msg_id=10)
        display_open(fd2, frame_id=11, msg_id=11, display_id=1)

        # Create one surface per session
        sid1, stride1, total1 = surface_create_raw(fd1, frame_id=3, msg_id=3, w=256, h=256, fmt=FMT_XRGB8888)
        sid2, stride2, total2 = surface_create_raw(fd2, frame_id=12, msg_id=12, w=256, h=256, fmt=FMT_XRGB8888)

        # Map each surface and paint a unique pattern
        st, msid1, mstride1, mtotal1 = map_surface(fd1, sid1)
        assert st == 0 and msid1 == sid1 and mstride1 == stride1 and mtotal1 == total1

        st, msid2, mstride2, mtotal2 = map_surface(fd2, sid2)
        assert st == 0 and msid2 == sid2 and mstride2 == stride2 and mtotal2 == total2

        mm1 = mmap.mmap(fd1, total1, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        mm2 = mmap.mmap(fd2, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            # Session 1: white
            mm1[:64] = b"\xff\xff\xff\x00" * 16
            mm1.flush()

            # Session 2: greenish
            mm2[:64] = b"\x00\xff\x00\x00" * 16
            mm2.flush()

            # Interleaved presents, verify isolation via cookie
            cookie1a = 0x1111111111111111
            cookie2a = 0x2222222222222222
            surface_present_raw(fd1, frame_id=4, msg_id=4, surface_id=sid1, cookie=cookie1a)
            surface_present_raw(fd2, frame_id=13, msg_id=13, surface_id=sid2, cookie=cookie2a)

            psid1, _flags1, pcookie1 = wait_presented(fd1, timeout_ms=1000)
            assert psid1 == sid1 and pcookie1 == cookie1a

            psid2, _flags2, pcookie2 = wait_presented(fd2, timeout_ms=1000)
            assert psid2 == sid2 and pcookie2 == cookie2a

            # Second round, reverse order
            cookie1b = 0xaaaaaaaaaaaaaaaa
            cookie2b = 0xbbbbbbbbbbbbbbbb
            surface_present_raw(fd2, frame_id=14, msg_id=14, surface_id=sid2, cookie=cookie2b)
            surface_present_raw(fd1, frame_id=5, msg_id=5, surface_id=sid1, cookie=cookie1b)

            psid2, _flags2, pcookie2 = wait_presented(fd2, timeout_ms=1000)
            assert psid2 == sid2 and pcookie2 == cookie2b

            psid1, _flags1, pcookie1 = wait_presented(fd1, timeout_ms=1000)
            assert psid1 == sid1 and pcookie1 == cookie1b

        finally:
            mm1.close()
            mm2.close()

        # Close session 1, session 2 must continue to function
        os.close(fd1)
        fd1 = -1

        # Re-map and present again on fd2 after the other session is gone
        st, msid2, mstride2, mtotal2 = map_surface(fd2, sid2)
        assert st == 0 and msid2 == sid2

        mm2 = mmap.mmap(fd2, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            mm2[:64] = b"\x00\x00\xff\x00" * 16  # red-ish
            mm2.flush()

            cookie2c = 0xcccccccccccccccc
            surface_present_raw(fd2, frame_id=15, msg_id=15, surface_id=sid2, cookie=cookie2c)

            psid2, _flags2, pcookie2 = wait_presented(fd2, timeout_ms=1000)
            assert psid2 == sid2 and pcookie2 == cookie2c
        finally:
            mm2.close()

        print("OK: Step 17 multi session interleaved present passed")

    finally:
        if fd1 != -1:
            os.close(fd1)
        os.close(fd2)


if __name__ == "__main__":
    main()
