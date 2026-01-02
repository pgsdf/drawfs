#!/usr/bin/env python3
import os, struct, errno, fcntl, mmap, time, select

DEV = "/dev/draw"

DRAWFS_MAGIC   = 0x31575244  # 'DRW1'
DRAWFS_VERSION = 0x0100      # 1.0

# Requests
REQ_HELLO          = 0x0001
REQ_DISPLAY_LIST   = 0x0010
REQ_DISPLAY_OPEN   = 0x0011
REQ_SURFACE_CREATE = 0x0020
REQ_SURFACE_PRESENT = 0x0022

# Replies and events
RPL_DISPLAY_LIST    = 0x8010
RPL_DISPLAY_OPEN    = 0x8011
RPL_SURFACE_CREATE  = 0x8020
RPL_SURFACE_PRESENT = 0x8022
EVT_SURFACE_PRESENTED = 0x9002

# Frame and message headers
fh_fmt = "<IHHII"   # magic, version, header_bytes, frame_bytes, frame_id
mh_fmt = "<HHIII"   # msg_type, flags, msg_bytes, msg_id, reserved

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
    frame_hdr = struct.pack(
        fh_fmt, DRAWFS_MAGIC, DRAWFS_VERSION, struct.calcsize(fh_fmt), frame_bytes, frame_id
    )
    frame = frame_hdr + body
    frame += b"\x00" * (frame_bytes - len(frame))
    return frame

def read_one(fd, timeout_ms=1000):
    p = select.poll()
    p.register(fd, select.POLLIN | getattr(select, "POLLRDNORM", 0))
    ev = p.poll(timeout_ms)
    if not ev:
        raise TimeoutError("Timed out waiting for reply or event")
    buf = os.read(fd, 4096)
    if len(buf) < struct.calcsize(fh_fmt) + struct.calcsize(mh_fmt):
        raise RuntimeError(f"Short read: {len(buf)} bytes")

    off = struct.calcsize(fh_fmt)
    msg_type, msg_flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off + payload_len]
    return msg_type, msg_id, payload

def decode_display_list(payload: bytes):
    # uint32 count; then repeats: uint32 id, uint16 w, uint16 h, uint32 refresh_mhz, uint32 flags
    if len(payload) < 4:
        raise RuntimeError("DISPLAY_LIST payload too small")
    (count,) = struct.unpack_from("<I", payload, 0)
    off = 4
    out = []
    for _ in range(count):
        did, w, h, refresh_mhz, flags = struct.unpack_from("<IHHII", payload, off)
        out.append((did, w, h, refresh_mhz, flags))
        off += struct.calcsize("<IHHII")
    return out

def decode_surface_create(payload: bytes):
    # int32 status; uint32 surface_id; uint32 stride; uint32 total_bytes
    return struct.unpack_from("<iIII", payload, 0)

def decode_surface_present_reply(payload: bytes):
    # int32 status; uint32 surface_id; uint64 cookie
    return struct.unpack_from("<iIQ", payload, 0)

def decode_surface_presented_event(payload: bytes):
    # uint32 surface_id; uint32 status; uint64 cookie
    return struct.unpack_from("<IIQ", payload, 0)

# ioctl helpers, matching FreeBSD sys/ioccom.h encoding used in earlier steps
IOC_INOUT = 0xC0000000
def _IOC(inout, group, num, length):
    return inout | ((length & 0x1fff) << 16) | ((group & 0xff) << 8) | (num & 0xff)
def _IOWR(group_chr, num, length):
    return _IOC(IOC_INOUT, ord(group_chr), num, length)

MAP_FMT = "<iIII"
MAP_SIZE = struct.calcsize(MAP_FMT)
DRAWFSGIOC_MAP_SURFACE = _IOWR('D', 0x02, MAP_SIZE)

def map_surface_ioctl(fd, surface_id: int):
    # struct drawfs_map_surface: { int32 status; uint32 surface_id; uint32 stride; uint32 total; }
    buf = bytearray(MAP_SIZE)
    struct.pack_into("<iI", buf, 0, 0, surface_id)
    fcntl.ioctl(fd, DRAWFSGIOC_MAP_SURFACE, buf, True)
    return struct.unpack_from(MAP_FMT, buf, 0)

def mmap_surface(fd, total_bytes: int):
    return mmap.mmap(fd, total_bytes, mmap.MAP_SHARED,
                    mmap.PROT_READ | mmap.PROT_WRITE, offset=0)

def fill_pattern(mm, stride: int, w: int, h: int, rgba32: int):
    # XRGB8888 stored little endian as BB GG RR XX for most tools,
    # but for our test we only need deterministic bytes.
    px = struct.pack("<I", rgba32)
    row = px * w
    for y in range(h):
        start = y * stride
        mm[start:start + 4*w] = row

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        # HELLO
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)]))
        _ = read_one(fd)

        # DISPLAY_LIST
        os.write(fd, make_frame(2, [make_msg(REQ_DISPLAY_LIST, 2, b"")]))
        t, mid, pl = read_one(fd)
        if t != RPL_DISPLAY_LIST:
            raise SystemExit(f"FAIL: expected DISPLAY_LIST reply 0x{RPL_DISPLAY_LIST:x}, got 0x{t:x}")
        displays = decode_display_list(pl)
        if not displays:
            raise SystemExit("FAIL: no displays reported")
        did = displays[0][0]
        print("DISPLAY_LIST:", displays)

        # DISPLAY_OPEN
        open_payload = struct.pack("<I", did)
        os.write(fd, make_frame(3, [make_msg(REQ_DISPLAY_OPEN, 3, open_payload)]))
        t, mid, pl = read_one(fd)
        if t != RPL_DISPLAY_OPEN:
            raise SystemExit(f"FAIL: expected DISPLAY_OPEN reply 0x{RPL_DISPLAY_OPEN:x}, got 0x{t:x}")

        # Create 3 surfaces 64x64 XRGB8888 (format=1)
        surfaces = []
        for i in range(3):
            w = 64
            h = 64
            fmt = 1
            flags = 0
            sc_req = struct.pack("<IIII", w, h, fmt, flags)
            os.write(fd, make_frame(10 + i, [make_msg(REQ_SURFACE_CREATE, 100 + i, sc_req)]))
            t, mid, pl = read_one(fd)
            if t != RPL_SURFACE_CREATE:
                raise SystemExit(f"FAIL: expected SURFACE_CREATE reply, got 0x{t:x}")
            st, sid, stride, total = decode_surface_create(pl)
            if st != 0 or sid == 0:
                raise SystemExit(f"FAIL: surface create failed status={st} sid={sid}")
            surfaces.append((sid, stride, total, w, h))
        print("SURFACES:", [(s[0], s[1], s[2]) for s in surfaces])

        # For each surface, map and write a unique pattern
        patterns = [0x00FFFFFF, 0x0000FF00, 0x00FF0000]  # white, green, red (XRGB)
        for (sid, stride, total, w, h), rgba in zip(surfaces, patterns):
            rep = map_surface_ioctl(fd, sid)
            if rep[0] != 0:
                raise SystemExit(f"FAIL: MAP_SURFACE failed for sid={sid} status={rep[0]}")
            mm = mmap_surface(fd, rep[3])
            try:
                fill_pattern(mm, rep[2], w, h, rgba)
                mm.flush()
                # quick readback of first pixel
                first = struct.unpack_from("<I", mm, 0)[0]
                if first != rgba:
                    raise SystemExit(f"FAIL: readback mismatch sid={sid} got=0x{first:08x} want=0x{rgba:08x}")
            finally:
                mm.close()

        # Present round robin and verify reply and event ordering and cookie integrity
        for i in range(9):
            sid, stride, total, w, h = surfaces[i % len(surfaces)]
            cookie = 0xABC00000_00000000 | i
            flags = 0
            present_req = struct.pack("<IIQ", sid, flags, cookie)
            os.write(fd, make_frame(50 + i, [make_msg(REQ_SURFACE_PRESENT, 200 + i, present_req)]))

            t, mid, pl = read_one(fd)
            if t != RPL_SURFACE_PRESENT:
                raise SystemExit(f"FAIL: expected SURFACE_PRESENT reply 0x{RPL_SURFACE_PRESENT:x}, got 0x{t:x}")
            st, sid_r, cookie_r = decode_surface_present_reply(pl)
            if st != 0 or sid_r != sid or cookie_r != cookie:
                raise SystemExit(f"FAIL: present reply mismatch st={st} sid={sid_r} cookie=0x{cookie_r:x}")

            t, mid, pl = read_one(fd)
            if t != EVT_SURFACE_PRESENTED:
                raise SystemExit(f"FAIL: expected SURFACE_PRESENTED event 0x{EVT_SURFACE_PRESENTED:x}, got 0x{t:x}")
            sid_e, st_e, cookie_e = decode_surface_presented_event(pl)
            if sid_e != sid or st_e != 0 or cookie_e != cookie:
                raise SystemExit(f"FAIL: presented event mismatch sid={sid_e} st={st_e} cookie=0x{cookie_e:x}")

        print("OK: Step 14 multi surface round robin present passed")
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
