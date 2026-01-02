# SECURITY

## Threat Model
- Untrusted user-space clients
- Malformed protocol messages
- Resource exhaustion attacks

## Security Principles
- No raw framebuffer access
- Kernel-enforced validation
- Per-session isolation
- Explicit privilege boundaries

## mmap Safety
- mmap is only permitted for kernel-allocated surface memory
- Surfaces must be explicitly selected via ioctl
- Size and access are strictly validated

## Future Work
- Capability-based access control
- SELinux / Capsicum integration
