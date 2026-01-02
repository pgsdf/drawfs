# drawfs and semadraw

## Tooling note

The reference integration work for SemaDraw assumes Zig 0.15.2 when Zig tooling is required.


semadraw is a user-space rendering and composition library.

## Relationship

- drawfs: kernel semantic boundary
- semadraw: policy, rendering, scene graph

semadraw talks directly to `/dev/draw`, creates surfaces,
maps them with mmap, renders, and will eventually present them.

This clean separation avoids embedding rendering policy in the kernel.
