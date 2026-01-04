# SECURITY

## Threat Model
- Untrusted user-space clients
- Malformed protocol messages
- Resource exhaustion attacks

## Resource exhaustion hardening

The module enforces conservative defaults to reduce trivial DoS by unbounded
surface creation:

- Maximum surfaces per session (`hw.drawfs.max_surfaces`, default: 64)
- Maximum bytes per surface (`hw.drawfs.max_surface_bytes`, default: 64MB)
- Maximum cumulative surface bytes per session (`hw.drawfs.max_session_surface_bytes`, default: 256MB)
- Maximum event queue bytes per session (`hw.drawfs.max_evq_bytes`, default: 8KB)

All limits are tunable at runtime via sysctl. Changes affect new operations only.

## Security Principles
- No raw framebuffer access
- Kernel-enforced validation
- Per-session isolation
- Explicit privilege boundaries

## Sysctl Configuration

The module exposes security-relevant settings under `hw.drawfs`:

### Device Permissions

Set via `loader.conf` (applied at module load):

```sh
# /boot/loader.conf
hw.drawfs.dev_uid=0        # Device owner UID (default: 0/root)
hw.drawfs.dev_gid=920      # Device group GID (default: 0/wheel)
hw.drawfs.dev_mode=0660    # Device permissions (default: 0600)
```

Example: Allow `video` group (GID 920) access:
```sh
echo 'hw.drawfs.dev_gid=920' >> /boot/loader.conf
echo 'hw.drawfs.dev_mode=0660' >> /boot/loader.conf
```

### mmap Gate

The `hw.drawfs.mmap_enabled` sysctl controls whether mmap is permitted:

```sh
# Disable mmap at runtime
sysctl hw.drawfs.mmap_enabled=0

# Re-enable mmap
sysctl hw.drawfs.mmap_enabled=1
```

When disabled, mmap returns `EPERM`. This can be used to:
- Restrict surface memory access in high-security environments
- Disable mmap temporarily for debugging

Default: enabled (1)

## mmap Safety
- mmap is only permitted for kernel-allocated surface memory
- Surfaces must be explicitly selected via ioctl
- Size and access are strictly validated
- mmap can be globally disabled via sysctl

## Future Work
- Capability-based access control
- SELinux / Capsicum integration
