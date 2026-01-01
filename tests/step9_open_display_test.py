import os, struct

DEV = "/dev/draw"
DRAWFS_MAGIC   = 0x31575244  # 'DRW1'
DRAWFS_VERSION = 0x0100

REQ_HELLO        = 0x0001
REQ_DISPLAY_LIST = 0x0010
REQ_DISPLAY_OPEN = 0x0011

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

def parse_reply(buf: bytes):
    magic, ver, hdr_bytes, frame_bytes, frame_id = struct.unpack_from(fh_fmt, buf, 0)
    if magic != DRAWFS_MAGIC:
        raise ValueError("bad magic")
    off = hdr_bytes
    msg_type, msg_flags, msg_bytes, msg_id, _rsv = struct.unpack_from(mh_fmt, buf, off)
    payload_off = off + struct.calcsize(mh_fmt)
    payload_len = msg_bytes - struct.calcsize(mh_fmt)
    payload = buf[payload_off:payload_off+payload_len]
    return msg_type, msg_id, payload

def decode_display_list(payload: bytes):
    (count,) = struct.unpack_from("<I", payload, 0)
    desc_fmt = "<IIIII"
    desc_sz = struct.calcsize(desc_fmt)
    displays = []
    for i in range(count):
        base = 4 + i * desc_sz
        display_id, w, h, refresh_mhz, flags = struct.unpack_from(desc_fmt, payload, base)
        displays.append((display_id, w, h, refresh_mhz, flags))
    return displays

def decode_display_open(payload: bytes):
    return struct.unpack_from("<iII", payload, 0)

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(1, [make_msg(REQ_HELLO, 1, hello_payload)]))
        _ = os.read(fd, 4096)

        os.write(fd, make_frame(2, [make_msg(REQ_DISPLAY_LIST, 2, b"")]))
        r = os.read(fd, 4096)
        _t, _id, payload = parse_reply(r)
        displays = decode_display_list(payload)
        print("DISPLAY_LIST:", displays)

        open_payload = struct.pack("<I", 1)
        os.write(fd, make_frame(3, [make_msg(REQ_DISPLAY_OPEN, 3, open_payload)]))
        r2 = os.read(fd, 4096)
        _t2, _id2, payload2 = parse_reply(r2)
        status, handle, active_id = decode_display_open(payload2)
        print(f"DISPLAY_OPEN: status={status} handle={handle} active_id={active_id}")

        bad_payload = struct.pack("<I", 99)
        os.write(fd, make_frame(4, [make_msg(REQ_DISPLAY_OPEN, 4, bad_payload)]))
        r3 = os.read(fd, 4096)
        _t3, _id3, payload3 = parse_reply(r3)
        status2, handle2, active_id2 = decode_display_open(payload3)
        print(f"DISPLAY_OPEN(bad): status={status2} handle={handle2} active_id={active_id2}")
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
