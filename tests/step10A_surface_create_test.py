import os, struct, errno

DEV = "/dev/draw"
DRAWFS_MAGIC   = 0x31575244  # 'DRW1'
DRAWFS_VERSION = 0x0100

REQ_HELLO          = 0x0001
REQ_DISPLAY_OPEN   = 0x0011
REQ_SURFACE_CREATE = 0x0020

FMT_XRGB8888 = 1

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

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)]))
        _ = os.read(fd, 4096)

        print("== Surface create before display open (expect errno.EINVAL) ==")
        sc_req = struct.pack("<IIII", 640, 480, FMT_XRGB8888, 0)
        os.write(fd, make_frame(2, [make_msg(REQ_SURFACE_CREATE, 2, sc_req)]))
        _t, _mid, pl = read_reply(fd)
        print("SURFACE_CREATE:", decode_surface_create(pl))

        print("== Display open then surface create (expect 0, surface_id>0) ==")
        open_payload = struct.pack("<I", 1)
        os.write(fd, make_frame(3, [make_msg(REQ_DISPLAY_OPEN, 3, open_payload)]))
        _ = os.read(fd, 4096)

        os.write(fd, make_frame(4, [make_msg(REQ_SURFACE_CREATE, 4, sc_req)]))
        _t2, _mid2, pl2 = read_reply(fd)
        print("SURFACE_CREATE:", decode_surface_create(pl2))

        print("== Unsupported format (expect errno.EPROTONOSUPPORT) ==")
        bad_req = struct.pack("<IIII", 64, 64, 999, 0)
        os.write(fd, make_frame(5, [make_msg(REQ_SURFACE_CREATE, 5, bad_req)]))
        _t3, _mid3, pl3 = read_reply(fd)
        print("SURFACE_CREATE:", decode_surface_create(pl3))
        print("errno.EPROTONOSUPPORT =", errno.EPROTONOSUPPORT)
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
