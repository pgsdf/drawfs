# drawfs Kernel Module, Step 11

Step 11 introduces a minimal surface backing store and mmap support.

## New ioctl

`DRAWFSGIOC_MAP_SURFACE` selects a surface on a given fd for mmap.

Request (in the same buffer):
- `uint32_t surface_id`

Reply:
- `int32_t status`
- `uint32_t surface_id`
- `uint32_t stride_bytes`
- `uint32_t bytes_total`

After a successful ioctl, user space can:

- `mmap(fd, bytes_total, PROT_READ|PROT_WRITE, MAP_SHARED, offset=0)`

The mapping returns a zero-filled buffer in `XRGB8888` format.

## Semantics

- Backing memory is per-surface, session-scoped.
- First map allocates a swap-backed `vm_object`.
- Future work will add PRESENT / FLIP to display.

## Tests

- `tests/step11_surface_mmap_test.py`
