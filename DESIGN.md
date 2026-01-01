# Design

drawfs provides a stable and auditable graphics substrate for FreeBSD.

## Principles

* Protocol first
* Minimal primitives
* Explicit object lifetimes
* Clear separation of mechanism and policy
* Hardware agnostic baseline
* Deterministic error semantics

## Why a semantic interface

A raw framebuffer interface is useful but incomplete for modern workflows.

drawfs is designed around semantics.

* Explicit resource creation
* Explicit mapping of buffers
* Explicit presentation (planned)
* Explicit event delivery (planned)

This supports higher level systems without forcing a specific desktop stack.

## Version 1 milestones

Implemented.
* Hello and negotiation
* Display enumeration and open
* Surface create and destroy
* Reply event queue with blocking reads
* poll readiness semantics
* mmap backing for surfaces (Step 11)

Planned next.
* Present and flip
* Damage tracking
* Input events
* Backend binding to vt or KMS

## Compatibility

The protocol is normative.
Existing message layouts must not change.
New features must be additive.
