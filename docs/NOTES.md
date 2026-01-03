# NOTES

Quick workflow for local development on FreeBSD 15.

## Install, build, load

From the repository root:

    sudo ./build.sh all

This performs:
- Install: rsync sources into /usr/src
- Build: make in /usr/src/sys/modules/drawfs
- Load: kldload the resulting drawfs.ko and create /dev/draw

## Run a test

Example:

    sudo python3 tests/step11_surface_mmap_test.py
