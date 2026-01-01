# SEMADRAW_INTEGRATION.md
## Semantic Integration Between drawfs and semadraw

### Overview

semadraw is a semantic graphics engine. drawfs anchors its intent in kernel validated truth.

---

## Division of Responsibility

drawfs defines what exists and what is valid. semadraw decides what to do with it.

---

## Semantic Startup Flow

open -> HELLO -> DISPLAY_LIST -> DISPLAY_OPEN

At completion semadraw has a semantic anchor to a display.

---

## Rendering Semantics

Rendering messages express intent relative to the bound display. drawfs validates context but never interprets pixels.

---

## Why semadraw Does Not Start With DRM

DRM is imperative and hardware specific. drawfs normalizes this into semantic truth.

---

## Failure Semantics

Rejected requests mean invalid intent, not undefined behavior. This enables recovery.

---

## Appendix A: Why semadraw Is Not a Compositor

Policy belongs in user space. The kernel validates, it does not decide.

---

## Appendix B: Wayland Comparison

Wayland requires global compositors and implicit timing. semadraw plus drawfs is explicit and local.

---

## Appendix C: Plan 9 Lineage

Plan 9 treated graphics as a file. drawfs treats graphics context as truth.

---

## Summary

drawfs provides semantic truth. semadraw provides semantic intent.
