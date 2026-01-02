# Kernel Architecture

This document describes the FreeBSD kernel module that implements `/dev/draw`.

## Scope

The kernel implements mechanism only.

* Protocol parsing and validation
* Session state and resource tables
* Reply and event queueing
* Blocking read plus wakeups
* `poll` readiness semantics
* Surface backing storage with `mmap` support (Step 11)

Everything else belongs in user space.

## Device model

`/dev/draw` is a character device.

The kernel module uses the following cdevsw hooks.

* `d_open`
  * Allocate a `drawfs_session`
  * Initialize locks and queues
* `d_close`
  * Free session objects
  * Deallocate surface backing memory objects
* `d_write`
  * Append bytes to an input buffer
  * Parse complete frames
  * Process messages
  * Enqueue replies and wake readers
* `d_read`
  * Blocking read of queued replies and events
  * Supports nonblocking semantics
* `d_poll`
  * Readable when the reply event queue is nonempty
* `d_ioctl`
  * Stats and diagnostics ioctls
  * Step 11 includes MAP_SURFACE ioctl
* `d_mmap_single` (Step 11)
  * Returns a vm object for the selected surface

## State and locking

Each session owns a mutex `s->lock`.

The session lock protects.

* Input buffer state
* Reply event queue
* Display state (active display id and handle state)
* Surface list and ids
* `map_surface_id` selection used for `mmap`

Locking rules.

* Hold the session lock when reading or writing any session fields above.
* Do not sleep while holding the lock unless required by kernel primitives that are safe under the lock.
* Keep protocol processing small and bounded.

## Readiness semantics

* `read` blocks until at least one reply event is queued.
* `poll` reports readable when a reply event is queued.
* Writers wake readers when new events are enqueued.

This model supports a simple event loop in user space.

## Surface backing and mapping (Step 11)

Surfaces have fields such as.

* width, height, format
* stride_bytes, bytes_total
* vm_object pointer (swap backed) when mapped

The mapping flow is.

1. User creates a surface.
2. User calls MAP_SURFACE ioctl with a surface id.
3. User calls `mmap(fd, bytes_total, PROT_READ|PROT_WRITE, MAP_SHARED, offset=0)`.
4. Kernel returns a swap backed vm object sized to `bytes_total`.

The mapping is session scoped. The selected surface id is stored in `map_surface_id` on that fd.

## Error semantics

drawfs replies report `status` as a FreeBSD errno value.

Examples.

* `EINVAL` is 22
* `ENOENT` is 2
* `EPROTONOSUPPORT` is 43 on FreeBSD

Clients must not hardcode Linux errno numbers.
