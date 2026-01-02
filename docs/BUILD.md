# Build and test (kmod)

This repository includes a small helper script, `build.sh`, that installs the kernel module
sources into your FreeBSD source tree, builds the module, loads it, and runs a selected test.

## Prerequisites

- FreeBSD 15
- Zig 0.15.2 (optional, for userspace samples)

- `rsync` installed (used by `build.sh install`)
- Python 3 installed (for tests)

## Quick start

From the repo root:

```sh
chmod +x build.sh
sudo ./build.sh all tests/step11_surface_mmap_test.py
```

That will:

1. Copy `sys/dev/drawfs` to `/usr/src/sys/dev/drawfs`
2. Copy `sys/modules/drawfs` to `/usr/src/sys/modules/drawfs`
3. Build the module via `/usr/src/sys/modules/drawfs`
4. `kldload` the resulting `drawfs.ko`
5. Run the selected test from `tests/`

## Common commands

```sh
sudo ./build.sh install
sudo ./build.sh build
sudo ./build.sh load
sudo ./build.sh unload
sudo ./build.sh test tests/step11_surface_mmap_test.py
```

## Verify you are building the intended sources

If you suspect a stale install under `/usr/src`, run:

```sh
./build.sh verify
```

It prints file mtimes and a few greps that help confirm the installed sources match the repo.
