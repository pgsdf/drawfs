#!/usr/bin/env python3
import os, struct

DEV = "/dev/draw"
DRAWFS_MAGIC   = 0x31575244
DRAWFS_VERSION = 0x0100

REQ_HELLO          = 0x0001
REQ_DISPLAY_OPEN   = 0x0011
REQ_SURFACE_CREATE = 0x0020
REQ_SURFACE_PRESENT= 0x0022

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

def read_reply(fd):
    buf = os.read(fd, 4096)
    off = struct.calcsize(fh_fmt)
    msg_type, _flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off+payload_len]
    return msg_type, msg_id, payload

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)]))
        os.read(fd, 4096)

        open_payload = struct.pack("<I", 1)
        os.write(fd, make_frame(2, [make_msg(REQ_DISPLAY_OPEN, 2, open_payload)]))
        os.read(fd, 4096)

        sc_req = struct.pack("<IIII", 256, 256, 1, 0)
        os.write(fd, make_frame(3, [make_msg(REQ_SURFACE_CREATE, 3, sc_req)]))
        _t, _mid, pl = read_reply(fd)
        st, sid, stride, total = struct.unpack_from("<iIII", pl, 0)
        print("SURFACE_CREATE:", (st, sid, stride, total))
        if st != 0:
            raise SystemExit("surface create failed")

        pres_req = struct.pack("<II", sid, 0)
        os.write(fd, make_frame(4, [make_msg(REQ_SURFACE_PRESENT, 4, pres_req)]))
        t, mid, pl = read_reply(fd)
        st, sid2, _r0, _r1 = struct.unpack_from("<iIII", pl, 0)
        print("SURFACE_PRESENT reply:", hex(t), mid, (st, sid2))
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
