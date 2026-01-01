import os, struct, select

DEV = "/dev/draw"
DRAWFS_MAGIC   = 0x31575244  # 'DRW1'
DRAWFS_VERSION = 0x0100      # 1.0

REQ_HELLO        = 0x0001
REQ_DISPLAY_LIST = 0x0010

def align4(n: int) -> int:
    return (n + 3) & ~3

fh_fmt = "<IHHII"
mh_fmt = "<HHIII"

def make_msg(msg_type: int, msg_id: int, payload: bytes) -> bytes:
    payload = payload or b""
    msg_bytes = align4(struct.calcsize(mh_fmt) + len(payload))
    msg_hdr = struct.pack(mh_fmt, msg_type, 0, msg_bytes, msg_id, 0)
    msg = msg_hdr + payload
    msg += b"\x00" * (msg_bytes - len(msg))
    return msg

def make_frame(frame_id: int, msgs: list) -> bytes:
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

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        print("== multi-message in one frame + poll readiness ==")
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)

        m1 = make_msg(REQ_HELLO, 101, hello_payload)
        m2 = make_msg(REQ_DISPLAY_LIST, 102, b"")
        frame = make_frame(10, [m1, m2])

        p = select.poll()
        p.register(fd, select.POLLIN | select.POLLRDNORM)

        before = p.poll(0)
        print("poll before write:", before)

        os.write(fd, frame)

        after = p.poll(1000)
        print("poll after write:", after)
        if not after:
            raise SystemExit("FAIL: poll did not report readable after write")

        read_reply(fd, "reply 1")
        read_reply(fd, "reply 2")

        print("PASS")
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
