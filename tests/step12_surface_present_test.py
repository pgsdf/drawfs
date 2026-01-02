#!/usr/bin/env python3
# Step 12: SURFACE_PRESENT end-to-end smoke test
#
# Flow:
#  1) HELLO
#  2) DISPLAY_OPEN (display_id=1)
#  3) SURFACE_CREATE (XRGB8888)
#  4) DRAWFSGIOC_MAP_SURFACE ioctl -> returns stride + total bytes
#  5) mmap() surface and write a simple pattern
#  6) SURFACE_PRESENT(surface_id)
#  7) Read reply + presented event

import os, struct, errno, fcntl, mmap, time

DEV = "/dev/draw"
DRAWFS_MAGIC   = 0x31575244  # 'DRW1'
DRAWFS_VERSION = 0x0100      # 1.0

# Requests
REQ_HELLO          = 0x0001
REQ_DISPLAY_OPEN   = 0x0011
REQ_SURFACE_CREATE = 0x0020
REQ_SURFACE_PRESENT= 0x0022

# Replies / events (from sys/dev/drawfs/drawfs_proto.h)
RPL_SURFACE_CREATE  = 0x8020
RPL_SURFACE_PRESENT = 0x8022
EVT_SURFACE_PRESENTED = 0x9002

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
        raise RuntimeError(f"short read: {len(buf)} bytes")
    off = struct.calcsize(fh_fmt)
    msg_type, _msg_flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off + payload_len]
    return msg_type, msg_id, payload

def xrgb8888_stride(width: int) -> int:
    return width * 4

# ioctl: DRAWFSGIOC_MAP_SURFACE _IOWR('D', 0x02, struct drawfs_map_surface)
# We use the kernel header layout, not a guessed userspace ioc number.
# The struct contains req + rep:
#   req: uint32 surface_id
#   rep: int32 status; uint32 surface_id; uint32 stride; uint32 total_bytes
#
# NOTE: The kernel interface uses a single in/out struct (see sys/dev/drawfs/drawfs_ioctl.h):
#   int32  status
#   uint32 surface_id  (input)
#   uint32 stride
#   uint32 total_bytes
REP_FMT = "<iIII"
REP_SIZE = struct.calcsize(REP_FMT)

def map_surface_ioctl(fd, surface_id: int):
    import sys
    # Compute ioctl number like sys/ioccom.h does for _IOWR.
    IOC_INOUT = 0xC0000000
    IOCPARM_MASK = 0x1fff
    def _IOC(inout, group, num, length):
        return inout | (((length & IOCPARM_MASK) << 16)) | ((group & 0xff) << 8) | (num & 0xff)
    def _IOWR(group_chr, num, length):
        return _IOC(IOC_INOUT, ord(group_chr), num, length)

    DRAWFSGIOC_MAP_SURFACE = _IOWR('D', 0x02, REP_SIZE)

    buf = bytearray(REP_SIZE)
    # status is output, surface_id is input
    struct.pack_into("<iI", buf, 0, 0, surface_id)
    fcntl.ioctl(fd, DRAWFSGIOC_MAP_SURFACE, buf, True)
    status, sid, stride, total = struct.unpack_from(REP_FMT, buf, 0)
    return status, sid, stride, total

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        # HELLO
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)]))
        _ = os.read(fd, 4096)

        # DISPLAY_OPEN(display_id=1)
        open_payload = struct.pack("<I", 1)
        os.write(fd, make_frame(2, [make_msg(REQ_DISPLAY_OPEN, 2, open_payload)]))
        _ = os.read(fd, 4096)

        # SURFACE_CREATE (256x256, XRGB8888 format=1, flags=0)
        w, h = 256, 256
        sc_req = struct.pack("<IIII", w, h, 1, 0)
        os.write(fd, make_frame(3, [make_msg(REQ_SURFACE_CREATE, 3, sc_req)]))
        msg_type, _mid, pl = read_one(fd)
        if msg_type != RPL_SURFACE_CREATE:
            raise SystemExit(f"FAIL: expected SURFACE_CREATE reply 0x{RPL_SURFACE_CREATE:x}, got 0x{msg_type:x}")
        st, sid, stride, total = struct.unpack_from("<iIII", pl, 0)
        print("SURFACE_CREATE:", (st, sid, stride, total))
        if st != 0:
            raise SystemExit("FAIL: surface create failed")

        # MAP_SURFACE ioctl
        st, sid2, stride2, total2 = map_surface_ioctl(fd, sid)
        print("MAP_SURFACE ioctl rep:", (st, sid2, stride2, total2))
        if st != 0:
            raise SystemExit("FAIL: map_surface ioctl failed")
        if sid2 != sid:
            raise SystemExit("FAIL: ioctl returned wrong surface_id")

        # mmap and draw a simple top-left checker pattern
        mm = mmap.mmap(fd, total2, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            # paint 64x64 alternating white and black pixels
            for y in range(64):
                row = bytearray(stride2)
                for x in range(64):
                    is_white = ((x >> 3) ^ (y >> 3)) & 1
                    # XRGB8888 in this prototype is written as 0x00RRGGBB little-endian bytes: BB GG RR 00
                    if is_white:
                        row[x*4:x*4+4] = b"\xff\xff\xff\x00"
                    else:
                        row[x*4:x*4+4] = b"\x00\x00\x00\x00"
                mm[y*stride2:(y+1)*stride2] = row
            mm.flush()
        finally:
            mm.close()

        # SURFACE_PRESENT(surface_id)
        # Must match struct drawfs_req_surface_present in sys/dev/drawfs/drawfs_proto.h:
        #   uint32 surface_id;
        #   uint32 reserved;
        #   uint64 cookie;
        # The cookie is echoed back in both the reply and the presented event.
        cookie = 0x1122334455667788
        sp_req = struct.pack("<IIQ", sid, 0, cookie)
        os.write(fd, make_frame(4, [make_msg(REQ_SURFACE_PRESENT, 4, sp_req)]))

        # Read reply (and then the presented event)
        msg_type, _mid, pl = read_one(fd)
        if msg_type != RPL_SURFACE_PRESENT:
            raise SystemExit(f"FAIL: expected SURFACE_PRESENT reply 0x{RPL_SURFACE_PRESENT:x}, got 0x{msg_type:x}")
        st, rep_surface_id, rep_cookie = struct.unpack_from("<iIQ", pl, 0)
        print("SURFACE_PRESENT reply:", (st, rep_surface_id, rep_cookie))
        if st != 0:
            raise SystemExit(f"FAIL: surface present status={st} ({errno.errorcode.get(st,'?')})")
        if rep_surface_id != sid or rep_cookie != cookie:
            raise SystemExit("FAIL: SURFACE_PRESENT reply mismatch (surface_id or cookie)")

        # Event: EVT_SURFACE_PRESENTED
        msg_type, _mid, pl = read_one(fd)
        if msg_type != EVT_SURFACE_PRESENTED:
            raise SystemExit(f"FAIL: expected SURFACE_PRESENTED event 0x{EVT_SURFACE_PRESENTED:x}, got 0x{msg_type:x}")
        ev_surface_id, ev_seqno, ev_cookie = struct.unpack_from("<IIQ", pl, 0)
        print("SURFACE_PRESENTED event:", (ev_surface_id, ev_seqno, ev_cookie))
        if ev_surface_id != sid:
            raise SystemExit("FAIL: event surface_id mismatch")
        if ev_cookie != cookie:
            raise SystemExit("FAIL: event cookie mismatch")

        print("OK: present path completed")

    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
