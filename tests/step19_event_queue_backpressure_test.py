#!/usr/bin/env python3
"""Step 19: Event queue backpressure

Goal
  Confirm the kernel enforces a bounded per-session output queue (events and replies).
  When the queue is full, subsequent writes should fail with ENOSPC until userland drains
  the device by reading.

Notes
  - This test intentionally *does not read* for a while to let the kernel queue grow.
  - Once ENOSPC is observed, we start reading and then verify writes succeed again.

Environment
  - FreeBSD 15
  - Python 3
"""

import os, struct, errno, time, fcntl

DEV = "/dev/draw"

DRAWFS_MAGIC   = 0x31575244
DRAWFS_VERSION = 0x0100

# Requests
REQ_HELLO          = 0x0001
REQ_DISPLAY_OPEN   = 0x0011
REQ_SURFACE_CREATE = 0x0020
REQ_SURFACE_PRESENT= 0x0022

# Protocol headers
FH_FMT = "<IHHII"   # magic, version, header_bytes, frame_bytes, frame_id
MH_FMT = "<HHIII"   # msg_type, flags, msg_bytes, msg_id, reserved

def align4(n: int) -> int:
    return (n + 3) & ~3

def make_msg(msg_type: int, msg_id: int, payload: bytes) -> bytes:
    payload = payload or b""
    msg_bytes = align4(struct.calcsize(MH_FMT) + len(payload))
    hdr = struct.pack(MH_FMT, msg_type, 0, msg_bytes, msg_id, 0)
    msg = hdr + payload
    msg += b"\x00" * (msg_bytes - len(msg))
    return msg

def make_frame(frame_id: int, msgs: list[bytes]) -> bytes:
    body = b"".join(msgs)
    frame_bytes = align4(struct.calcsize(FH_FMT) + len(body))
    hdr = struct.pack(FH_FMT, DRAWFS_MAGIC, DRAWFS_VERSION, struct.calcsize(FH_FMT), frame_bytes, frame_id)
    frame = hdr + body
    frame += b"\x00" * (frame_bytes - len(frame))
    return frame

def read_one(fd: int, timeout_ms: int = 2000) -> bytes:
    # Simple blocking read with deadline using polling sleeps.
    deadline = time.time() + (timeout_ms / 1000.0)
    while True:
        try:
            return os.read(fd, 4096)
        except InterruptedError:
            continue
        except OSError as e:
            raise
        if time.time() > deadline:
            raise RuntimeError("timeout waiting for message")

def parse_first_msg(frame: bytes):
    if len(frame) < struct.calcsize(FH_FMT) + struct.calcsize(MH_FMT):
        raise RuntimeError("short frame")
    off = struct.calcsize(FH_FMT)
    msg_type, msg_flags, msg_bytes, msg_id, _ = struct.unpack_from(MH_FMT, frame, off)
    payload_off = off + struct.calcsize(MH_FMT)
    payload_len = msg_bytes - struct.calcsize(MH_FMT)
    payload = frame[payload_off:payload_off + payload_len]
    return msg_type, msg_id, payload

def decode_surface_create(payload: bytes):
    # <iIII => status, surface_id, stride, total
    return struct.unpack_from("<iIII", payload, 0)

def send(fd: int, frame: bytes):
    os.write(fd, frame)

# Stats ioctl: _IOR('D', 0x01, struct drawfs_stats)
# FreeBSD _IOR: ((0x40000000) | (((size) & 0x1fff) << 16) | ((group) << 8) | (num))
# struct drawfs_stats is 9*8 + 2*4 = 80 bytes
DRAWFSGIOC_STATS = 0x40504401  # _IOR('D', 0x01, 80)

def get_stats(fd: int):
    buf = bytearray(80)
    fcntl.ioctl(fd, DRAWFSGIOC_STATS, buf)
    # Parse: 9 uint64s, 2 uint32s
    vals = struct.unpack("<QQQQQQQQQII", buf)
    return {
        'frames_received': vals[0],
        'frames_processed': vals[1],
        'events_enqueued': vals[5],
        'events_dropped': vals[6],
        'evq_depth': vals[9],
        'inbuf_bytes': vals[10],
    }

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        # HELLO
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        send(fd, make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)]))

        # DISPLAY_OPEN
        open_payload = struct.pack("<I", 1)
        send(fd, make_frame(2, [make_msg(REQ_DISPLAY_OPEN, 2, open_payload)]))

        # SURFACE_CREATE 256x256
        sc_req = struct.pack("<IIII", 256, 256, 1, 0)
        send(fd, make_frame(3, [make_msg(REQ_SURFACE_CREATE, 3, sc_req)]))

        # Drain just enough to get the surface id (replies are queued too).
        # We might get HELLO/DISPLAY replies first, so loop until we see SURFACE_CREATE reply.
        sid = None
        stride = total = None
        for _ in range(10):
            fr = read_one(fd, 2000)
            mt, _mid, pl = parse_first_msg(fr)
            if mt == 0x8020:  # RPL_SURFACE_CREATE
                st, sid, stride, total = decode_surface_create(pl)
                print("SURFACE_CREATE:", (st, sid, stride, total))
                if st != 0:
                    raise SystemExit("FAIL: surface create failed")
                break
        if sid is None:
            raise SystemExit("FAIL: did not receive SURFACE_CREATE reply")

        # Now intentionally *stop reading* and spam SURFACE_PRESENT to fill the kernel queue.
        cookie = 0x1234567890ABCDEF
        present_payload = struct.pack("<IIQ", sid, 0, cookie)  # surface_id, flags, cookie
        hit = False
        for i in range(1, 5000):
            frame = make_frame(100 + i, [make_msg(REQ_SURFACE_PRESENT, 100 + i, present_payload)])
            try:
                send(fd, frame)
            except OSError as e:
                if e.errno == errno.ENOSPC:
                    print(f"OK: hit backpressure (ENOSPC) after {i} presents")
                    hit = True
                    break
                raise

        if not hit:
            raise SystemExit("FAIL: did not hit backpressure limit")

        # Debug: check queue depth before draining
        stats = get_stats(fd)
        print(f"DEBUG: evq_depth={stats['evq_depth']}, events_enqueued={stats['events_enqueued']}, events_dropped={stats['events_dropped']}")

        # Try non-blocking read on a fresh fd to see what happens
        # (note: this opens a NEW session, so it won't see our queue - just testing the mechanism)
        fd_nb = os.open(DEV, os.O_RDWR | os.O_NONBLOCK)
        try:
            test_read = os.read(fd_nb, 4096)
            print(f"DEBUG: non-blocking NEW fd read got {len(test_read)} bytes (unexpected!)")
        except BlockingIOError:
            print("DEBUG: non-blocking NEW fd returned EAGAIN (expected - new session is empty)")
        except Exception as e:
            print(f"DEBUG: non-blocking NEW fd error: {e}")
        finally:
            os.close(fd_nb)

        # The real test: try poll() to see if our fd is readable
        import select
        readable, _, _ = select.select([fd], [], [], 0.1)
        if fd in readable:
            print("DEBUG: select() says fd is readable - queue should have data")
        else:
            print("DEBUG: select() says fd is NOT readable - poll isn't seeing the queue!")

        # Drain some frames to make space again.
        # Use select() before each read to avoid blocking
        import select
        drained = 0
        start = time.time()
        while drained < 200 and (time.time() - start) < 2.0:
            readable, _, _ = select.select([fd], [], [], 0.5)
            if fd not in readable:
                print(f"DEBUG: select returned not readable after draining {drained}")
                break
            fr = os.read(fd, 4096)
            if not fr:
                break
            drained += 1
        print(f"OK: drained {drained} frames")

        # Verify we can write again after draining.
        try:
            send(fd, make_frame(9000, [make_msg(REQ_SURFACE_PRESENT, 9000, present_payload)]))
        except OSError as e:
            if e.errno == errno.ENOSPC:
                raise SystemExit("FAIL: still ENOSPC after draining")
            raise

        print("OK: Step 19 event queue backpressure passed")
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
