#ifndef _DEV_DRAWFS_DRAWFS_INTERNAL_H_
#define _DEV_DRAWFS_DRAWFS_INTERNAL_H_

#include <sys/param.h>
#include <sys/systm.h>
#include <sys/malloc.h>
#include <sys/queue.h>
#include <sys/lock.h>
#include <sys/mutex.h>
#include <sys/condvar.h>
#include <sys/selinfo.h>
#include <vm/vm.h>
#include <vm/vm_object.h>

#include "drawfs.h"
#include "drawfs_ioctl.h"

MALLOC_DECLARE(M_DRAWFS);

/*
 * Tunable resource limits (defined in drawfs.c, exposed via sysctl).
 */
extern int drawfs_max_evq_bytes;
extern int drawfs_max_surfaces;
extern long drawfs_max_surface_bytes;
extern long drawfs_max_session_surface_bytes;

/*
 * Debug counters for vm_object lifecycle tracking (defined in drawfs.c).
 */
extern volatile u_int drawfs_vmobj_allocs;
extern volatile u_int drawfs_vmobj_deallocs;

/*
 * Event queue entry for outbound frames (replies and async events).
 */
struct drawfs_event {
    TAILQ_ENTRY(drawfs_event) link;
    size_t len;
    uint8_t *bytes;
};

/*
 * Surface object representing a client-allocated drawing surface.
 */
struct drawfs_surface {
    TAILQ_ENTRY(drawfs_surface) link;
    uint32_t id;
    uint32_t width_px;
    uint32_t height_px;
    uint32_t format;
    uint32_t stride_bytes;
    uint32_t bytes_total;
    vm_object_t vmobj;
};

TAILQ_HEAD(drawfs_surface_list, drawfs_surface);
TAILQ_HEAD(drawfs_eventq, drawfs_event);

/*
 * Per-file-descriptor session state.
 */
struct drawfs_session {
    struct mtx lock;
    struct cv cv;
    struct selinfo sel;

    struct drawfs_eventq evq;
    size_t evq_bytes;
    bool closing;

    uint32_t next_out_frame_id;

    /* Input accumulation */
    uint8_t *inbuf;
    size_t in_len;
    size_t in_cap;

    /* Display binding (Step 9) */
    uint32_t active_display_id;
    uint32_t map_surface_id; /* surface selected for mmap */
    uint32_t active_surface_id; /* last presented surface */
    uint32_t next_display_handle;
    uint32_t active_display_handle;

    /* Surface objects (Step 10A) */
    struct drawfs_surface_list surfaces;
    uint32_t next_surface_id;

    /* Step 18 hardening: surface resource accounting */
    uint32_t surfaces_count;
    uint64_t surfaces_bytes;

    /* Stats (per session) */
    struct drawfs_stats stats;
};

#endif /* _DEV_DRAWFS_DRAWFS_INTERNAL_H_ */
