# ROADMAP

## Phase 0: Specification
* Protocol definition
* State machines
* Error semantics
* Test harness

## Phase 1: Kernel prototype
* Character device protocol
* Blocking reads and poll semantics
* Display discovery and open
* Surface lifecycle (create and destroy)
* mmap backed surface memory and MAP_SURFACE ioctl
* Present request, present reply, and presented event
* Present sequencing guarantees
* Round robin surface selection and present
* Session cleanup and reopen
* Multi session isolation
* Multi session interleaved present

## Phase 2: Real display bring up
* DRM KMS integration
* Mode setting and page flip
* Tie presents to vblank or page flip completion
* Optional dumb buffer or GEM integration for zero copy paths

## Phase 3: Performance and ergonomics
* Damage tracking and partial updates
* Frame pacing and back pressure signals
* Per display present queues
* Better statistics and observability






## Backlog and recommended optional work
* Run a KNF and formatting pass on sys/dev/drawfs/drawfs.c and split it into smaller translation units once the API stabilizes
* Add a stress test that creates, maps, presents, destroys, and closes sessions in a loop to catch vm_object leaks and swap backed growth
* Add tests for destroy while mapped, close while mapped, multiple mmaps, and fork then close
* Add lightweight observability via sysctl counters for sessions, surfaces, vm_objects, bytes_total, and present events
* Add protocol fuzzing at the frame and message layers to harden length, alignment, and bounds checking
* Add a permission model for display open and present (root only by default, with an option for a dedicated group)
* Add multi display selection and hotplug semantics once DRM KMS integration lands
* Add damage tracking so clients can present dirty rectangles instead of full surface swaps
* Add a future path for zero copy or DMA BUF style sharing where available
