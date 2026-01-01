# STATE MACHINES

This document defines the normative state machines for drawfs objects.

## Session
States:
- NEW
- ACTIVE
- CLOSED

Transitions occur on HELLO, close, or error.

## Display
- ENUMERATED
- OPEN
- CLOSED

## Surface
- CREATED
- MAPPED (optional)
- DESTROYED

## Invariants
- Surfaces require an open display
- mmap is only valid for a selected surface
- Destroyed objects are immediately invalid
