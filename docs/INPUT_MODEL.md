# Input Model

This document defines the intended input model for drawfs.

Input is not implemented yet. This is a design target for future steps.

## Goals

* Do not expose raw input devices to unprivileged clients.
* Provide ordered event delivery per session.
* Support user space policy for focus and routing.

## Concepts

* Input events are delivered as messages on the same read stream as replies.
* Event ordering is preserved per session.
* The policy daemon may multiplex device input to sessions based on focus.

## Security

Input routing is a policy decision.
The kernel should provide only minimal primitives needed to deliver events safely.

## Planned event types

* Key press and release
* Pointer motion and buttons
* Touch events
* Window focus changes (policy driven)

## Relationship to semadraw

semadraw can consume input events but should not implement system wide policy.
A policy daemon can route input to semadraw clients.
