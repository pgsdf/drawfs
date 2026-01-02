# drawfs

drawfs is a prototype kernel device and message protocol for a minimal graphics path:

- A userspace client writes framed messages to `/dev/draw`
- The kernel queues replies and events back to the same file descriptor via `read(2)`
- Shared pixel surfaces are exposed to userspace via an explicit `MAP_SURFACE` ioctl followed by `mmap(2)`

This repository is intended as a stepping stone for integrating a fast, predictable drawing path into SemaDraw.

## Platform

- FreeBSD 15
- Python 3 (tests)
- Zig 0.15.2 (optional, for SemaDraw integration work)

## Quick start

This repo includes `build.sh` to install the kernel sources into `/usr/src`, build the module, and load it.

```sh
./build.sh install
./build.sh build
./build.sh load
./build.sh test
```

The `test` action runs the current end to end tests in `tests/`.

## Repository layout

- `sys/dev/drawfs/` kernel device implementation
- `sys/modules/drawfs/` kmod build glue
- `tests/` python and C tests (step based)
- `docs/` design and protocol documentation

## License

See `LICENSE`.
