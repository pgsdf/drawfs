import os, struct, errno

DEV = "/dev/draw"
DRAWFS_MAGIC   = 0x31575244  # 'DRW1'
DRAWFS_VERSION = 0x0100

REQ_HELLO           = 0x0001
REQ_DISPLAY_OPEN    = 0x0011
REQ_SURFACE_CREATE  = 0x0020
REQ_SURFACE_DESTROY = 0x0021

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
    magic, ver, hdr_bytes, frame_bytes, frame_id = struct.unpack_from(fh_fmt, buf, 0)
    off = hdr_bytes
    msg_type, msg_flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off+payload_len]
    return msg_type, msg_id, payload

def decode_surface_create(payload: bytes):
    return struct.unpack_from("<iIII", payload, 0)

def decode_surface_destroy(payload: bytes):
    return struct.unpack_from("<iI", payload, 0)

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)]))
        _ = os.read(fd, 4096)

        open_payload = struct.pack("<I", 1)
        os.write(fd, make_frame(2, [make_msg(REQ_DISPLAY_OPEN, 2, open_payload)]))
        _ = os.read(fd, 4096)

        sc_req = struct.pack("<IIII", 320, 240, 1, 0)
        os.write(fd, make_frame(3, [make_msg(REQ_SURFACE_CREATE, 3, sc_req)]))
        _t, _mid, pl = read_reply(fd)
        st, sid, stride, total = decode_surface_create(pl)
        print("SURFACE_CREATE:", (st, sid, stride, total))
        if st != 0 or sid == 0:
            raise SystemExit("FAIL: expected a valid surface_id")

        print("== Destroy existing surface (expect 0) ==")
        dreq = struct.pack("<I", sid)
        os.write(fd, make_frame(4, [make_msg(REQ_SURFACE_DESTROY, 4, dreq)]))
        _t2, _mid2, pl2 = read_reply(fd)
        dst, dsid = decode_surface_destroy(pl2)
        print("SURFACE_DESTROY:", (dst, dsid))

        print("== Destroy same surface again (expect errno.ENOENT) ==")
        os.write(fd, make_frame(5, [make_msg(REQ_SURFACE_DESTROY, 5, dreq)]))
        _t3, _mid3, pl3 = read_reply(fd)
        dst2, dsid2 = decode_surface_destroy(pl3)
        print("SURFACE_DESTROY:", (dst2, dsid2))
        print("errno.ENOENT =", errno.ENOENT)

        print("== Destroy surface_id=0 (expect errno.EINVAL) ==")
        os.write(fd, make_frame(6, [make_msg(REQ_SURFACE_DESTROY, 6, struct.pack("<I", 0))]))
        _t4, _mid4, pl4 = read_reply(fd)
        dst3, dsid3 = decode_surface_destroy(pl4)
        print("SURFACE_DESTROY:", (dst3, dsid3))
        print("errno.EINVAL =", errno.EINVAL)

    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
