# ROADMAP

## Phase 0: Specification
- Protocol definition
- State machines
- Error semantics
- Test harness

## Phase 1: Kernel Prototype (current)
- Character device protocol
- Blocking reads and poll semantics
- Display discovery and open
- Surface lifecycle
- mmap-backed surface memory

## Phase 2: Real Display Bring-up
- DRM/KMS integration
- Mode setting
- Atomic present path

## Phase 3: User Environment
- Reference compositor
- Window management
- Input integration

## Phase 4: Optimization
- Zero-copy paths
- GPU acceleration
- Scheduling and batching
