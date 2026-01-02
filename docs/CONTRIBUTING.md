# Contributing

Thank you for contributing to drawfs.

## Before you start

* Search existing issues and discussions.
* For protocol changes, open an issue before implementing.
* Keep changes small and reviewable.

## Compatibility rules

* Backward compatibility is mandatory for protocol v1.
* Do not change existing message layouts.
* Add new messages and new fields only with explicit versioning or capability negotiation.

## Documentation requirements

Any change to the protocol or kernel behavior must include updates to.

* `PROTOCOL.md` for normative wire format changes
* `COMPLIANCE.md` for interoperability requirements
* `ARCHITECTURE_KMOD.md` for kernel responsibilities and locking rules

## Development workflow

* Prefer tests in `tests/` that exercise user space visible behavior.
* Include a minimal reproduction script for bugs.
* Keep kernel changes auditable and bounded.

## Submitting changes

* Use clear commit messages.
* Include the problem statement and the approach.
* Include results: build output and test output.
