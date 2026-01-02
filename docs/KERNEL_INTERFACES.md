# Kernel Interfaces

This document describes the FreeBSD kernel behavior of `/dev/draw`.

## Device node

* Path: `/dev/draw`
* Type: character device
* Access: root for early development, later tightened by devfs rules and policy

## Open and close

* `open` allocates a session.
* `close` frees session state, surfaces, and backing objects.

## Write

* Accepts arbitrary chunking.
* Buffers incomplete frames.
* Validates frame headers and message headers.
* Processes complete messages in order.

## Read

* Returns queued replies and events.
* If the queue is empty, blocks unless nonblocking mode is requested.
* The unit of data returned is an encoded frame that wraps one reply message today.
  Future implementations may bundle replies and events per read.

## poll and kqueue

* Readable when at least one reply or event is queued.

## ioctl

Implemented ioctls.

* STATS: returns counters for frames, messages, and bytes.
* MAP_SURFACE (Step 11): selects a surface for `mmap` on this fd.

## mmap

* `mmap` is supported via `d_mmap_single`.
* Mapping must use offset 0.
* Mapping size must be nonzero and must not exceed the selected surface bytes_total.
* Memory is swap backed and shared between kernel and user space.

## Error reporting

Protocol replies use FreeBSD errno values.

Clients must not hardcode numbers from other systems.
