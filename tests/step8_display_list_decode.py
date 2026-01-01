import os, struct

DEV = "/dev/draw"
DRAWFS_MAGIC   = 0x31575244  # 'DRW1'
DRAWFS_VERSION = 0x0100

REQ_HELLO        = 0x0001
REQ_DISPLAY_LIST = 0x0010

fh_fmt = "<IHHII"
mh_fmt = "<HHIII"

def align4(n: int) -> int:
    return (n + 3) & ~3

def make_frame(frame_id: int, msg_type: int, msg_id: int, payload: bytes) -> bytes:
    payload = payload or b""
    msg_bytes = align4(struct.calcsize(mh_fmt) + len(payload))
    msg_hdr = struct.pack(mh_fmt, msg_type, 0, msg_bytes, msg_id, 0)
    msg = msg_hdr + payload
    msg += b"\x00" * (msg_bytes - len(msg))

    frame_bytes = align4(struct.calcsize(fh_fmt) + len(msg))
    frame_hdr = struct.pack(fh_fmt, DRAWFS_MAGIC, DRAWFS_VERSION, struct.calcsize(fh_fmt), frame_bytes, frame_id)
    frame = frame_hdr + msg
    frame += b"\x00" * (frame_bytes - len(frame))
    return frame

def parse_reply(buf: bytes):
    if len(buf) < struct.calcsize(fh_fmt) + struct.calcsize(mh_fmt):
        raise ValueError("reply too small")
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
    print("display count:", count)
    desc_fmt = "<IIIII"
    desc_sz = struct.calcsize(desc_fmt)
    for i in range(count):
        base = 4 + i * desc_sz
        display_id, w, h, refresh_mhz, flags = struct.unpack_from(desc_fmt, payload, base)
        print(f"  display[{i}] id={display_id} {w}x{h} refresh_mhz={refresh_mhz} flags=0x{flags:x}")

def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        hello_payload = struct.pack("<HHII", 1, 0, 0, 65536)
        os.write(fd, make_frame(1, REQ_HELLO, 1, hello_payload))
        _ = os.read(fd, 4096)

        os.write(fd, make_frame(2, REQ_DISPLAY_LIST, 2, b""))
        r = os.read(fd, 4096)
        msg_type, msg_id, payload = parse_reply(r)
        print(f"DISPLAY_LIST reply msg_type=0x{msg_type:x} msg_id={msg_id} payload_bytes={len(payload)}")
        decode_display_list(payload)
    finally:
        os.close(fd)

if __name__ == "__main__":
    main()
