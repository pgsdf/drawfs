import os, struct, fcntl, mmap, select

DEV = "/dev/draw"

DRAWFS_MAGIC   = 0x31575244
DRAWFS_VERSION = 0x0100

REQ_HELLO           = 0x0001
REQ_DISPLAY_OPEN    = 0x0011
REQ_SURFACE_CREATE  = 0x0020
REQ_SURFACE_PRESENT = 0x0022

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

def read_one_message(fd):
    buf = os.read(fd, 4096)
    off = struct.calcsize(fh_fmt)
    msg_type, _flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off+payload_len]
    return msg_type, msg_id, payload

# ioctl numbers must match sys/dev/drawfs/drawfs_ioctl.h
IOC_INOUT = 0xC0000000
def _IOC(inout, group, num, length):
    return inout | ((length & 0x1fff) << 16) | ((group & 0xff) << 8) | (num & 0xff)
def _IOWR(group_chr, num, length):
    return _IOC(IOC_INOUT, ord(group_chr), num, length)

MAP_FMT = "<iIII"
MAP_SIZE = struct.calcsize(MAP_FMT)
DRAWFSGIOC_MAP_SURFACE = _IOWR('D', 0x02, MAP_SIZE)

def map_surface_ioctl(fd, surface_id: int):
    buf = bytearray(MAP_SIZE)
    struct.pack_into("<iI", buf, 0, 0, surface_id)
    fcntl.ioctl(fd, DRAWFSGIOC_MAP_SURFACE, buf, True)
    return struct.unpack_from(MAP_FMT, buf, 0)

def decode_surface_create(payload: bytes):
    return struct.unpack_from("<iIII", payload, 0)

def decode_surface_present_reply(payload: bytes):
    return struct.unpack_from("<iIQ", payload, 0)

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        p = select.poll()
        p.register(fd, select.POLLIN | select.POLLRDNORM)

        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)]))
        _ = os.read(fd, 4096)

        open_payload = struct.pack("<I", 1)
        os.write(fd, make_frame(2, [make_msg(REQ_DISPLAY_OPEN, 2, open_payload)]))
        _ = os.read(fd, 4096)

        sc_req = struct.pack("<IIII", 256, 256, 1, 0)
        os.write(fd, make_frame(3, [make_msg(REQ_SURFACE_CREATE, 3, sc_req)]))
        _t, _mid, pl = read_one_message(fd)
        st, sid, stride, total = decode_surface_create(pl)
        print("SURFACE_CREATE:", (st, sid, stride, total))
        if st != 0:
            raise SystemExit("FAIL: surface create failed")

        rep = map_surface_ioctl(fd, sid)
        print("MAP_SURFACE ioctl rep:", rep)
        if rep[0] != 0:
            raise SystemExit("FAIL: map surface ioctl failed")

        mm = mmap.mmap(fd, rep[3], mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=0)
        try:
            mm[:64] = b"\xff\xff\xff\x00" * 16
            mm.flush()
        finally:
            mm.close()

        cookie = 0x1122334455667788
        present_req = struct.pack("<IIQ", sid, 0, cookie)
        os.write(fd, make_frame(4, [make_msg(REQ_SURFACE_PRESENT, 4, present_req)]))

        ev = p.poll(1000)
        if not ev:
            raise SystemExit("FAIL: poll did not report readable after present")

        t1, mid1, pl1 = read_one_message(fd)
        st2, sid2, cookie2 = decode_surface_present_reply(pl1)
        print("SURFACE_PRESENT reply:", (st2, sid2, hex(cookie2)))
        if st2 != 0 or sid2 != sid or cookie2 != cookie:
            raise SystemExit("FAIL: present reply unexpected")

        ev2 = p.poll(1000)
        if not ev2:
            raise SystemExit("FAIL: poll did not report readable for presented event")

        t2, mid2, pl2 = read_one_message(fd)
        esid, _rsv, ecookie = struct.unpack_from("<IIQ", pl2, 0)
        print("SURFACE_PRESENTED event:", (esid, hex(ecookie)))
        if esid != sid or ecookie != cookie:
            raise SystemExit("FAIL: event payload unexpected")

        print("Step 12 OK")
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
