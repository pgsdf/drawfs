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

### SURFACE_PRESENT 0x0022

Payload.

* surface_id: u32
* flags: u32 (reserved, must be zero)
* cookie: u64 (client-chosen tracking value)

Reply payload.

* status: i32
* surface_id: u32
* cookie: u64

Semantics.

* Notifies the kernel that the surface is ready for presentation.
* Requires a valid, mapped surface.
* Invalid surface_id returns ENOENT.
* The reply confirms the request was accepted.
* An async SURFACE_PRESENTED event is enqueued after the reply.

## Event messages

Event message types use the 0x9xxx range.

Events are asynchronous notifications delivered on the read stream alongside replies.
Clients must handle interleaved replies and events.

### SURFACE_PRESENTED 0x9002

Payload.

* surface_id: u32
* reserved: u32 (zero)
* cookie: u64

Semantics.

* Delivered after a SURFACE_PRESENT request is processed.
* The cookie matches the value from the corresponding request.
* Multiple SURFACE_PRESENTED events for the same surface may be coalesced under backpressure.

## Step 11 mapping semantics

Mapping uses ioctl and mmap, not protocol messages.

See `KERNEL_INTERFACES.md` and `ARCHITECTURE_KMOD.md` for details.

## Version compatibility

### Protocol versions

| Component | Version | Identifier |
|-----------|---------|------------|
| drawfs protocol | v1.0 | `0x0100` |
| semadraw IPC | v0.1 | major=0, minor=1 |
| SDCS command stream | v0.1 | major=0, minor=1 |

### Version negotiation

During HELLO handshake:
1. Client sends its version (client_major, client_minor)
2. Server responds with its version (server_major, server_minor)
3. Major version mismatch = incompatible, connection refused
4. Minor version mismatch = backward compatible, use lower version features

### Cross-component compatibility

drawfs v1.0 is compatible with semadraw v0.1:
- The semadraw drawfs backend correctly implements drawfs v1.0 protocol
- SDCS command streams are rendered by the drawfs backend, not passed through the protocol
- Version differences are at the semantic layer, not the wire protocol

## Alignment requirements

Different protocols have different alignment requirements:

| Protocol | Alignment | Padding |
|----------|-----------|---------|
| drawfs frames/messages | 4-byte | Zero-filled |
| SDCS command stream | 8-byte | Zero-filled |

When SDCS data is embedded in drawfs surfaces (via mmap), alignment boundaries
must be respected. The SDCS header is 64 bytes (8-byte aligned), and each
command record is padded to 8-byte boundaries.

## Forward compatibility

* New messages must be additive.
* Existing payload layouts must not change.
* Capability negotiation may be added later, but v1 remains stable.
