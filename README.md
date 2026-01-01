# drawfs

drawfs is a minimal, kernel-mediated graphics interface for FreeBSD inspired by Plan 9 style drawing.

Repository:
https://github.com/pgsdf/drawfs

## Purpose

drawfs provides a stable, versioned kernel interface for graphics that avoids direct framebuffer exposure. All drawing, presentation, and synchronization are mediated through explicit protocol messages and kernel-managed objects.

## Architecture Overview

- Character device: `/dev/draw`
- Framed, versioned message protocol
- Per-file-descriptor session state
- Explicit displays, surfaces, and presentation semantics
- mmap is used only for kernel-approved surface memory

## Current Status

Implemented:
- Session management
- HELLO handshake
- Display enumeration and open
- Surface create and destroy
- Surface mmap selection via ioctl
- Blocking read, poll readiness, and event delivery

In progress:
- Present / fence semantics
- Buffer lifecycle rules
- KMS-backed display binding

See ROADMAP.md for details.
