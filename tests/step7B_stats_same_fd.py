import os, struct, fcntl, select

DEV = "/dev/draw"
DRAWFS_MAGIC   = 0x31575244  # 'DRW1'
DRAWFS_VERSION = 0x0100      # 1.0

REQ_HELLO        = 0x0001
REQ_DISPLAY_LIST = 0x0010

def align4(n: int) -> int:
    return (n + 3) & ~3

fh_fmt = "<IHHII"
mh_fmt = "<HHIII"

# Must match sys/dev/drawfs/drawfs_ioctl.h
ST_FMT = "<QQQQQQQQII"
ST_SIZE = struct.calcsize(ST_FMT)

IOC_OUT = 0x40000000
def _IOC(inout, group, num, length):
    return inout | ((length & 0x1fff) << 16) | ((group & 0xff) << 8) | (num & 0xff)
def _IOR(group_chr, num, length):
    return _IOC(IOC_OUT, ord(group_chr), num, length)

DRAWFSGIOC_STATS = _IOR('D', 0x01, ST_SIZE)

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

def read_reply(fd, label):
    r = os.read(fd, 4096)
    print(f"{label} bytes", len(r))
    print(r.hex())
    return r

def read_stats(fd):
    buf = bytearray(ST_SIZE)
    fcntl.ioctl(fd, DRAWFSGIOC_STATS, buf, True)
    return struct.unpack(ST_FMT, buf)

def print_stats(tag, st):
    (frames_received, frames_processed, frames_invalid,
     messages_processed, messages_unsupported,
     events_enqueued, events_dropped,
     bytes_in, bytes_out,
     evq_depth, inbuf_bytes) = st

    print(f"== stats: {tag} ==")
    print("frames_received      ", frames_received)
    print("frames_processed     ", frames_processed)
    print("frames_invalid       ", frames_invalid)
    print("messages_processed   ", messages_processed)
    print("messages_unsupported ", messages_unsupported)
    print("events_enqueued      ", events_enqueued)
    print("events_dropped       ", events_dropped)
    print("bytes_in             ", bytes_in)
    print("bytes_out            ", bytes_out)
    print("evq_depth            ", evq_depth)
    print("inbuf_bytes          ", inbuf_bytes)

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        print("== Step 7B: activity + stats on same fd ==")

        st0 = read_stats(fd)
        print_stats("initial", st0)

        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        m1 = make_msg(REQ_HELLO, 201, hello_payload)
        m2 = make_msg(REQ_DISPLAY_LIST, 202, b"")
        frame = make_frame(20, [m1, m2])  # multi-message frame

        p = select.poll()
        p.register(fd, select.POLLIN | select.POLLRDNORM)

        os.write(fd, frame)

        ev = p.poll(1000)
        print("poll after write:", ev)
        if not ev:
            raise SystemExit("FAIL: poll did not report readable")

        read_reply(fd, "reply 1")
        read_reply(fd, "reply 2")

        st1 = read_stats(fd)
        print_stats("after traffic", st1)

        expected_out = 44 + 36
        if st1[8] != expected_out:
            print(f"NOTE: bytes_out expected {expected_out}, got {st1[8]}")
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
