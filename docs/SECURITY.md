# SECURITY

## Threat Model
- Untrusted user-space clients
- Malformed protocol messages
- Resource exhaustion attacks

## Resource exhaustion hardening

The module enforces conservative defaults to reduce trivial DoS by unbounded
surface creation:

- Maximum surfaces per session
- Maximum bytes per surface
- Maximum cumulative surface bytes per session

These values can be made configurable via sysctl later.

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
