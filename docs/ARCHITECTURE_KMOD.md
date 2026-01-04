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

## Source Files

The kernel module is split across multiple files for maintainability:

| File | Description |
|------|-------------|
| `drawfs.c` | Device operations (cdevsw), session lifecycle, message dispatch |
| `drawfs_surface.c` | Surface create/destroy/lookup, mmap backing store |
| `drawfs_frame.c` | Frame/message validation and building |
| `drawfs_internal.h` | Shared struct definitions (session, surface, event) |
| `drawfs_surface.h` | Surface API prototypes |
| `drawfs_frame.h` | Frame API prototypes |
| `drawfs.h` | Public constants (device name, limits) |
| `drawfs_proto.h` | Protocol structs and message types |

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

The session lock protects:

* Event queue (`evq`, `evq_bytes`)
* Session state (`closing` flag, `active_display_*`, `map_surface_id`)
* Input buffer (`inbuf`, `in_len`, `in_cap`)
* Statistics counters (`stats.*`)
* Condition variable and select info (`cv`, `sel`)
* Surface list (`surfaces`, `surfaces_count`, `surfaces_bytes`)

Locking rules:

* Never hold `s->lock` while calling `malloc()` with `M_WAITOK`
* Never hold `s->lock` when calling `vm_pager_allocate` or `vm_object_deallocate`
* Device callbacks (`d_open`, `d_close`, `d_read`, `d_write`, `d_poll`) acquire lock as needed
* Helper functions document whether they acquire lock or expect caller to hold it
* Keep protocol processing small and bounded

See the locking comments in `drawfs.c` and `drawfs_surface.c` for per-function documentation.

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

## Sysctl Configuration

The module exposes tunable parameters under `hw.drawfs`:

### Security

| Sysctl | Default | Description |
|--------|---------|-------------|
| `hw.drawfs.dev_uid` | 0 | Device node owner UID (at load) |
| `hw.drawfs.dev_gid` | 0 | Device node group GID (at load) |
| `hw.drawfs.dev_mode` | 0600 | Device node permissions (at load) |
| `hw.drawfs.mmap_enabled` | 1 | Allow mmap (runtime toggle) |

### Resource Limits

| Sysctl | Default | Description |
|--------|---------|-------------|
| `hw.drawfs.max_evq_bytes` | 8192 | Max event queue bytes per session |
| `hw.drawfs.max_surfaces` | 64 | Max surfaces per session |
| `hw.drawfs.max_surface_bytes` | 64MB | Max bytes per surface |
| `hw.drawfs.max_session_surface_bytes` | 256MB | Max cumulative surface bytes per session |

Device permission sysctls are applied at module load time via `loader.conf`.
All other sysctls can be changed at runtime and affect new operations.

### Debug

| Sysctl | Type | Description |
|--------|------|-------------|
| `hw.drawfs.vmobj_allocs` | read-only | Total vm_object allocations (cumulative) |
| `hw.drawfs.vmobj_deallocs` | read-only | Total vm_object deallocations (cumulative) |

These counters track global vm_object lifecycle for leak detection.
`vmobj_allocs - vmobj_deallocs` should equal zero after all sessions close.

See `docs/SECURITY.md` for configuration examples.

## Error semantics

drawfs replies report `status` as a FreeBSD errno value.

Examples.

* `EINVAL` is 22
* `ENOENT` is 2
* `EPROTONOSUPPORT` is 43 on FreeBSD

Clients must not hardcode Linux errno numbers.

## Stats ioctl

The `DRAWFSGIOC_STATS` ioctl returns per-session statistics in a `struct drawfs_stats`:

| Field | Type | Description |
|-------|------|-------------|
| `frames_received` | uint64 | Total frames received from client |
| `frames_processed` | uint64 | Frames successfully processed |
| `frames_invalid` | uint64 | Frames rejected (malformed) |
| `messages_processed` | uint64 | Messages successfully processed |
| `messages_unsupported` | uint64 | Messages with unknown type |
| `events_enqueued` | uint64 | Total events queued (cumulative) |
| `events_dropped` | uint64 | Events dropped due to queue full |
| `bytes_in` | uint64 | Total bytes received |
| `bytes_out` | uint64 | Total bytes sent |
| `evq_depth` | uint32 | Current number of events in queue |
| `inbuf_bytes` | uint32 | Bytes in input buffer (partial frame) |
| `evq_bytes` | uint32 | Current bytes in event queue |
| `surfaces_count` | uint32 | Current number of live surfaces |
| `surfaces_bytes` | uint64 | Total bytes allocated to surfaces |

The last three fields (`evq_bytes`, `surfaces_count`, `surfaces_bytes`) provide
real-time observability into session resource usage for debugging and monitoring.

## Compatibility

### Tested Platforms

| FreeBSD Version | Kernel Type | Status |
|-----------------|-------------|--------|
| 15.0-RELEASE-p1 | Non-debug (GENERIC) | ✅ All tests pass |
| 15.0-RELEASE-p1 | Debug (WITNESS) | Pending |

### Testing on Debug Kernel

To verify behavior with WITNESS lock debugging:

```sh
# Check if WITNESS is enabled
sysctl kern.conftxt | grep WITNESS

# Run tests and check for lock order violations
sudo ./build.sh test
dmesg | grep -i witness
```

WITNESS catches lock order violations and sleep-while-holding-lock bugs that
may not manifest on non-debug kernels.
