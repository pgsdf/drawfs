# DESIGN.md
## drawfs Design, Semantics, and Rationale

### Purpose

**drawfs** is a kernel mediated, message oriented graphics control interface for FreeBSD.

It exists to provide a **semantic boundary** between user space graphics systems and kernel validated display state. It does not draw, compose, or render. It establishes **what is true** and **what is valid**.

---

## Core Principle: Semantics Over Mechanism

drawfs is intentionally semantic, not imperative.

The kernel does not accept commands like draw this or present now. Instead it validates intent and reports truth.

---

## What Semantic Means

A semantic interface defines relationships and validity rather than procedures.

drawfs answers:
- What displays exist
- Which display a session is bound to
- Whether a request is valid
- Whether replies are available

It does not answer how or when pixels appear.

---

## Session Semantics

Each open file descriptor represents an isolated semantic session with private state, queues, and bindings.

There is no implicit global state.

---

## Framing as Semantic Boundary

Frames are atomic units of intent. Messages are single semantic operations. Partial frames have no meaning.

---

## Display Semantics

### DISPLAY_LIST
Declares kernel truth about available displays. No allocation or rendering capability is implied.

### DISPLAY_OPEN
Binds a session context to a display. This establishes meaning, not mode.

---

## Blocking and Readiness Semantics

Blocking read waits for semantic replies. Poll readiness indicates at least one complete reply exists.

---

## Error Semantics

All errors are explicit replies. Nothing is silently dropped.

---

## Observability

Statistics ioctls provide semantic introspection, not debugging output.

---

## Appendix A: Why This Is Not Wayland

Wayland is imperative and compositor centric. drawfs is declarative, kernel validated, and policy free.

---

## Appendix B: Plan 9 Comparison

Plan 9 inspired the philosophy. drawfs modernizes it with explicit framing, versioning, and observability.

---

## Summary

drawfs establishes semantic truth. User space builds policy. Rendering is orthogonal.
