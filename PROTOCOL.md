# Protocol

This document is normative.

drawfs protocol v1 defines frame and message formats and the semantics of required requests.

## Endianness and alignment

* All fields are little endian.
* All message sizes and frame sizes are padded to 4 byte alignment.
* Padding bytes are zero.

## Frame header

FrameHeader, 16 bytes.

* magic: u32, value 0x31575244 (ASCII DRW1)
* version: u16, value 0x0100 for v1.0
* header_bytes: u16, size of the frame header (16)
* frame_bytes: u32, total size of the frame including header and padding
* frame_id: u32, client chosen id

## Message header

MessageHeader, 16 bytes.

* msg_type: u16
* msg_flags: u16
* msg_bytes: u32, total size of the message including header and padding
* msg_id: u32, client chosen id
* reserved: u32, must be zero

## Reply messages

Reply message types set the high bit 0x8000.

Example.
* Request: 0x0010
* Reply:   0x8010

## Required requests

### HELLO 0x0001

Payload.

* client_major: u16
* client_minor: u16
* client_flags: u32
* max_reply_bytes: u32

Reply payload.

* status: i32
* server_major: u16
* server_minor: u16
* server_flags: u32
* max_reply_bytes: u32

### DISPLAY_LIST 0x0010

No payload.

Reply payload.

* status: i32
* count: u32
* repeated count times:
  * display_id: u32
  * width: u32
  * height: u32
  * refresh_mhz: u32
  * flags: u32

### DISPLAY_OPEN 0x0011

Payload.

* display_id: u32

Reply payload.

* status: i32
* handle: u32
* active_display_id: u32

### SURFACE_CREATE 0x0020

Payload.

* width: u32
* height: u32
* format: u32 (v1 supports XRGB8888 = 1)
* flags: u32

Reply payload.

* status: i32
* surface_id: u32
* stride_bytes: u32
* bytes_total: u32

Semantics.

* Requires an active display.
* Allocates a new surface id.
* Does not imply mapping or presentation.

### SURFACE_DESTROY 0x0021

Payload.

* surface_id: u32

Reply payload.

* status: i32
* surface_id: u32

Semantics.

* Removes the surface from the session.
* Invalid id returns ENOENT.
* surface_id 0 returns EINVAL.

## Step 11 mapping semantics

Mapping uses ioctl and mmap, not protocol messages.

See `KERNEL_INTERFACES.md` and `ARCHITECTURE_KMOD.md` for details.

## Forward compatibility

* New messages must be additive.
* Existing payload layouts must not change.
* Capability negotiation may be added later, but v1 remains stable.
