# Decisions

This file is a lightweight architectural decision record.

## 001 Protocol first

drawfs defines a stable protocol before building large subsystems.
This supports multiple implementations and long term compatibility.

## 002 Minimal primitives

The kernel exports a small set of primitives.
Everything else is built on top in user space.

## 003 Kernel mediated resources

Kernel code manages resources that require privilege or global coordination.

Examples.
* Device access
* Surface memory mapping objects
* Readiness notification

## 004 Policy in user space

Windowing, focus, and composition policy live in user space.

The kernel is not a compositor.

## 005 Session scoped object model

Objects are scoped to a single open file descriptor.
Closing the fd reclaims resources.
This makes resource lifetime explicit and auditable.

## 006 mmap backing is swap backed

Surface backing storage is implemented using swap backed vm objects.
This avoids exposing device physical memory early and keeps the first version simple.
