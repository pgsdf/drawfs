import os, struct, errno, fcntl, mmap

DEV = "/dev/draw"
DRAWFS_MAGIC   = 0x31575244
DRAWFS_VERSION = 0x0100

REQ_HELLO          = 0x0001
REQ_DISPLAY_OPEN   = 0x0011
REQ_SURFACE_CREATE = 0x0020

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
    msg_type, msg_flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off+payload_len]
    return msg_type, msg_id, payload

def decode_surface_create(payload: bytes):
    return struct.unpack_from("<iIII", payload, 0)

# ioctl helpers
IOC_INOUT = 0xC0000000
def _IOC(inout, group, num, length):
    return inout | ((length & 0x1fff) << 16) | ((group & 0xff) << 8) | (num & 0xff)
def _IOWR(group_chr, num, length):
    return _IOC(IOC_INOUT, ord(group_chr), num, length)

MAP_FMT = "<I" + "x"*0  # req is uint32 surface_id
REP_FMT = "<iIII"
REP_SIZE = struct.calcsize(REP_FMT)

DRAWFSGIOC_MAP_SURFACE = _IOWR('D', 0x02, REP_SIZE)

def map_surface_ioctl(fd, surface_id: int):
    # struct drawfs_map_surface: { int32 status; uint32 surface_id; uint32 stride; uint32 total; }
    buf = bytearray(REP_SIZE)
    struct.pack_into("<iI", buf, 0, 0, surface_id)
    fcntl.ioctl(fd, DRAWFSGIOC_MAP_SURFACE, buf, True)
    return struct.unpack_from(REP_FMT, buf, 0)

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        # HELLO
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)]))
        _ = os.read(fd, 4096)

        # DISPLAY_OPEN
        open_payload = struct.pack("<I", 1)
        os.write(fd, make_frame(2, [make_msg(REQ_DISPLAY_OPEN, 2, open_payload)]))
        _ = os.read(fd, 4096)

        # SURFACE_CREATE 256x256
        sc_req = struct.pack("<IIII", 256, 256, 1, 0)
        os.write(fd, make_frame(3, [make_msg(REQ_SURFACE_CREATE, 3, sc_req)]))
        _t, _mid, pl = read_reply(fd)
        st, sid, stride, total = decode_surface_create(pl)
        print("SURFACE_CREATE:", (st, sid, stride, total))
        if st != 0:
            raise SystemExit("FAIL: surface create failed")

        # Select for mmap
        rep = map_surface_ioctl(fd, sid)
        print("MAP_SURFACE ioctl rep:", rep)
        if rep[0] != 0:
            raise SystemExit("FAIL: map_surface ioctl failed")

        # mmap and write a simple pattern into first row
        mm = mmap.mmap(fd, rep[3], mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            # write 16 pixels of white in XRGB8888
            mm[:64] = b"\xff\xff\xff\x00" * 16
            mm.flush()
            # read back
            back = mm[:64]
            assert back == b"\xff\xff\xff\x00" * 16
            print("MMAP write/readback OK")
        finally:
            mm.close()

    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
