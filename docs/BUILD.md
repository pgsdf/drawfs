# Building drawfs

This repository contains a prototype FreeBSD kernel module and user space tests for the DrawFS protocol.

## Supported platform

- FreeBSD 15
- amd64 (current focus)

## Tooling

Required:

- FreeBSD base toolchain (clang, make)
- FreeBSD src tree installed at `/usr/src`
- Python 3 for the test suite

Optional:

- Zig 0.15.2 (reserved for upcoming user space components and integration work, not required for the kernel module)

## Quick start

From the repository root:

```sh
# Install sources into /usr/src and build the kernel module
sh ./build.sh

# Install, build, and load the module
sh ./build.sh load
```

`build.sh` performs these actions in order:

1. Copies `sys/dev/drawfs` and `sys/modules/drawfs` into the local src tree (default `/usr/src`) using `rsync`
2. Builds the module from `/usr/src/sys/modules/drawfs`
3. Prints the module object directory path
4. Optionally unloads and loads `drawfs.ko` when invoked with `load`

You can override the src tree path:

```sh
SRCROOT=/path/to/src sh ./build.sh load
```

## Running tests

All tests live in `tests/`.

Step 11 mmap test:

```sh
cd tests
sudo python3 step11_surface_mmap_test.py
```

Step 12 surface present test:

```sh
cd tests
sudo python3 step12_surface_present_test.py
```

## Notes

- The module currently creates `/dev/draw` and implements a subset of the protocol sufficient for the tests.
- The module is still a prototype. Expect interfaces and message types to evolve quickly.
