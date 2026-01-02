#!/usr/bin/env python3
"""Step 13: present sequencing and event ordering smoke test.

Validates:
  - SURFACE_PRESENT reply status is 0 for valid surface/display
  - A SURFACE_PRESENTED event follows each successful present
  - The cookie in the reply matches the cookie in the event
  - Multiple presents are processed in order (best-effort check)

Run:
  sudo python3 tests/step13_present_sequence_test.py
"""
import os, struct, fcntl, select, time

DEV = "/dev/draw"
DRAWFS_MAGIC   = 0x31575244  # 'DRW1'
DRAWFS_VERSION = 0x0100      # 1.0

REQ_HELLO          = 0x0001
REQ_DISPLAY_LIST   = 0x0010
REQ_DISPLAY_OPEN   = 0x0011
REQ_SURFACE_CREATE = 0x0020
REQ_SURFACE_PRESENT= 0x0022

RPL_DISPLAY_LIST   = 0x8010
RPL_DISPLAY_OPEN   = 0x8011
RPL_SURFACE_CREATE = 0x8020
RPL_SURFACE_PRESENT= 0x8022

EVT_SURFACE_PRESENTED = 0x9022

fh_fmt = "<IHHII"
mh_fmt = "<HHIII"

def align4(n: int) -> int:
    return (n + 3) & ~3

def make_msg(msg_type: int, msg_id: int, payload: bytes) -> bytes:
    payload = payload or b""
    msg_bytes = align4(struct.calcsize(mh_fmt) + len(payload))
    msg_hdr = struct.pack(mh_fmt, msg_type, 0, msg_bytes, msg_id, 0)
    msg = msg_hdr + payload
    msg += b"\x00" * (msg_bytes - len(msg))
    return msg

def make_frame(frame_id: int, msgs: list[bytes]) -> bytes:
    body = b"".join(msgs)
    frame_bytes = align4(struct.calcsize(fh_fmt) + len(body))
    frame_hdr = struct.pack(fh_fmt, DRAWFS_MAGIC, DRAWFS_VERSION, struct.calcsize(fh_fmt), frame_bytes, frame_id)
    frame = frame_hdr + body
    frame += b"\x00" * (frame_bytes - len(frame))
    return frame

def read_one(fd):
    buf = os.read(fd, 4096)
    if len(buf) < struct.calcsize(fh_fmt) + struct.calcsize(mh_fmt):
        raise RuntimeError("short read")
    off = struct.calcsize(fh_fmt)
    msg_type, _flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off+payload_len]
    return msg_type, msg_id, payload

def req_hello(fd):
    pl = struct.pack("<HHII", 1, 0, 0, 65536)
    os.write(fd, make_frame(1, [make_msg(REQ_HELLO, 1, pl)]))
    _ = read_one(fd)

def req_display_list(fd):
    os.write(fd, make_frame(2, [make_msg(REQ_DISPLAY_LIST, 2, b"")]))
    t, _mid, pl = read_one(fd)
    assert t == RPL_DISPLAY_LIST
    count = struct.unpack_from("<I", pl, 0)[0]
    if count < 1:
        raise SystemExit("FAIL: no displays reported")
    # first record: id,w,h,refresh_mhz,flags
    did, w, h, hz, fl = struct.unpack_from("<IIIII", pl, 4)
    return did, w, h, hz, fl

def req_display_open(fd, display_id: int):
    os.write(fd, make_frame(3, [make_msg(REQ_DISPLAY_OPEN, 3, struct.pack("<I", display_id))]))
    t, _mid, pl = read_one(fd)
    assert t == RPL_DISPLAY_OPEN
    status, handle, active_id = struct.unpack_from("<iII", pl, 0)
    if status != 0:
        raise SystemExit(f"FAIL: DISPLAY_OPEN status={status}")
    return handle, active_id

def req_surface_create(fd, w: int, h: int, fmt: int = 1):
    # req: width,height,format,flags
    os.write(fd, make_frame(4, [make_msg(REQ_SURFACE_CREATE, 4, struct.pack("<IIII", w, h, fmt, 0))]))
    t, _mid, pl = read_one(fd)
    assert t == RPL_SURFACE_CREATE
    status, sid, stride, total = struct.unpack_from("<iIII", pl, 0)
    if status != 0:
        raise SystemExit(f"FAIL: SURFACE_CREATE status={status}")
    return sid, stride, total

# ioctl helpers must match drawfs_ioctl.h in-kernel
IOC_INOUT = 0xC0000000
def _IOC(inout, group, num, length):
    return inout | ((length & 0x1fff) << 16) | ((group & 0xff) << 8) | (num & 0xff)
def _IOWR(group_chr, num, length):
    return _IOC(IOC_INOUT, ord(group_chr), num, length)

MAP_FMT = "<iIII"  # struct drawfs_map_surface (status, surface_id, stride, total)
MAP_SIZE = struct.calcsize(MAP_FMT)
DRAWFSGIOC_MAP_SURFACE = _IOWR('D', 0x02, MAP_SIZE)

def map_surface_ioctl(fd, surface_id: int):
    buf = bytearray(MAP_SIZE)
    struct.pack_into('<iI', buf, 0, 0, surface_id)
    fcntl.ioctl(fd, DRAWFSGIOC_MAP_SURFACE, buf, True)
    return struct.unpack_from(MAP_FMT, buf, 0)

def req_surface_present(fd, surface_id: int, cookie: int, flags: int = 0):
    pl = struct.pack("<IIQ", surface_id, flags, cookie)
    os.write(fd, make_frame(10, [make_msg(REQ_SURFACE_PRESENT, 10, pl)]))
    t, _mid, pl = read_one(fd)
    assert t == RPL_SURFACE_PRESENT
    status, sid, rep_cookie = struct.unpack_from("<iIQ", pl, 0)
    return status, sid, rep_cookie

def read_presented_event(fd):
    t, _mid, pl = read_one(fd)
    if t != EVT_SURFACE_PRESENTED:
        raise SystemExit(f"FAIL: expected SURFACE_PRESENTED event (0x{EVT_SURFACE_PRESENTED:x}), got 0x{t:x}")
    surface_id, status, cookie = struct.unpack_from("<IiQ", pl, 0)
    return surface_id, status, cookie

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        p = select.poll()
        p.register(fd, select.POLLIN | getattr(select, "POLLRDNORM", 0))

        req_hello(fd)
        did, w, h, hz, fl = req_display_list(fd)
        _handle, _active = req_display_open(fd, did)

        sid, stride, total = req_surface_create(fd, 256, 256, 1)
        st, sid2, stride2, total2 = map_surface_ioctl(fd, sid)
        if st != 0:
            raise SystemExit(f"FAIL: MAP_SURFACE status={st}")
        if total2 != total:
            raise SystemExit("FAIL: MAP_SURFACE total mismatch")

        # do 3 presents with distinct cookies and ensure reply+event match
        cookies = []
        for i in range(3):
            cookie = (int(time.time_ns()) ^ (i * 0x9e3779b97f4a7c15)) & 0xFFFFFFFFFFFFFFFF
            cookies.append(cookie)
            status, rsid, rcookie = req_surface_present(fd, sid, cookie, 0)
            if status != 0:
                raise SystemExit(f"FAIL: SURFACE_PRESENT status={status}")
            if rsid != sid or rcookie != cookie:
                raise SystemExit("FAIL: SURFACE_PRESENT reply mismatch")
            # poll should show readable for the event
            ev = p.poll(1000)
            if not ev:
                raise SystemExit("FAIL: poll did not show readable for event")
            esid, estatus, ecookie = read_presented_event(fd)
            if esid != sid or estatus != 0 or ecookie != cookie:
                raise SystemExit("FAIL: SURFACE_PRESENTED event mismatch")

        print("OK: Step 13 present sequencing passed")
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
