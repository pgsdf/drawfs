# Architecture

drawfs provides a minimal semantic graphics interface for FreeBSD.

At a high level, drawfs separates mechanism from policy.

## Components

* Kernel device: `/dev/draw`
  * Parses and validates frames and messages
  * Tracks session scoped objects (displays, surfaces)
  * Queues replies and events
  * Provides blocking read and readiness notification
  * Provides surface backing memory via `mmap` (Step 11)
* Optional user space policy daemon: `drawd` (planned)
  * Focus and input routing
  * Multi client composition policy
  * Security policy, permissions, and isolation
* Client libraries (planned)
  * Frame and message encode decode
  * Capability negotiation helpers
  * Convenience wrappers for surfaces and presentation

## Data flow

1. A client opens `/dev/draw` and sends `HELLO`.
2. The client queries `DISPLAY_LIST` and then `DISPLAY_OPEN`.
3. The client creates one or more surfaces.
4. The client selects a surface for mapping and uses `mmap` to obtain a writable pixel buffer.
5. The client renders into the mapped buffer.
6. Presentation semantics are added in a later step (planned).

## Objects and lifetimes

* Session
  * One open file descriptor is one session.
  * All objects are session scoped.
  * Closing the fd frees session resources.
* Display
  * A display id is enumerated from `DISPLAY_LIST`.
  * `DISPLAY_OPEN` activates a display for the session.
* Surface
  * Created after a display is active.
  * Backed by memory and mapped to user space.
  * Explicitly destroyed or freed when the session closes.

## Concurrency and ordering

* Writes are accepted in any chunking.
* Frames and messages are processed in order per session.
* Replies are emitted in order of processing.
* `read` blocks when no replies are queued unless nonblocking is requested.
* `poll` and `kqueue` indicate readability when replies or events are queued.

## Security posture

drawfs aims to be auditable and to keep kernel responsibilities narrow.

* Kernel code does not implement window management.
* Kernel code does not implement compositing policy.
* Kernel code does not expose raw input devices to clients.
