# Compliance

This document defines minimum interoperability requirements for drawfs protocol v1 servers and clients.

The intent is predictable behavior across implementations.

## Definitions

* Server: the `/dev/draw` provider (kernel module or an alternative implementation)
* Client: any process that opens `/dev/draw` and speaks the protocol
* Reply: a response message emitted by the server
* Event: an asynchronous message emitted by the server

## Protocol version

* Servers and clients must support protocol version 1.0.
* Clients must send `HELLO` before other requests.
* Servers must reply to `HELLO` with negotiated limits.

## Required requests (v1 baseline)

* `HELLO`
* `DISPLAY_LIST`
* `DISPLAY_OPEN`
* `SURFACE_CREATE`
* `SURFACE_DESTROY`

## Required behavior

### Framing
* Servers must accept partial frames across multiple writes.
* Servers must accept multiple messages in a single frame.
* Servers must validate `frame_bytes` and `msg_bytes` alignment and bounds.

### Reads and readiness
* If no replies or events are queued, `read` must block unless nonblocking I O is requested.
* `poll` and `kqueue` must indicate readability when replies or events are queued.

### Errors
* Servers must return FreeBSD errno values in `status` fields.
* Clients must treat errno numbers as platform specific and must not hardcode Linux values.

## Step 11 compliance (surface mapping)

If a server implements Step 11 mapping, it must provide.

* MAP_SURFACE ioctl that selects a surface for mapping on the calling fd
* `mmap` support that returns a buffer sized to `bytes_total`
* Shared mappings that allow user space writes

Clients that use Step 11 must.

* Call MAP_SURFACE before `mmap`
* Use `bytes_total` from the reply when sizing the mapping

## Optional features

These are not required for v1 baseline, but must be negotiated or documented when present.

* Present or flip
* Damage rectangles
* Input events
* Multiple displays
* Multiple active surfaces per display
