#ifndef _DEV_DRAWFS_DRAWFS_H_
#define _DEV_DRAWFS_DRAWFS_H_

#define DRAWFS_DEVNAME "draw"
#define DRAWFS_NODEPATH "/dev/draw"

#define DRAWFS_MAX_FRAME_BYTES   (1024 * 1024)

/* Maximum bytes queued for events and replies per session. */
#define DRAWFS_MAX_EVQ_BYTES (8 * 1024)
#define DRAWFS_MAX_EVENT_BYTES   (64 * 1024)
#define DRAWFS_MAX_MSG_BYTES     (512 * 1024)

/*
 * Step 18 hardening limits
 *
 * These prevent trivial resource exhaustion via unbounded surface creation.
 * They are intentionally conservative for early bring-up.
 */
#define DRAWFS_MAX_SURFACES              64
#define DRAWFS_MAX_SURFACE_BYTES         (64ULL * 1024ULL * 1024ULL)
#define DRAWFS_MAX_SESSION_SURFACE_BYTES (256ULL * 1024ULL * 1024ULL)

#endif
