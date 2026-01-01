#ifndef _DEV_DRAWFS_DRAWFS_IOCTL_H_
#ifdef _KERNEL
#include <sys/stdint.h>
#else
#include <stdint.h>
#endif
#define _DEV_DRAWFS_DRAWFS_IOCTL_H_

#include <sys/ioccom.h>
#include <sys/types.h>

struct drawfs_stats {
    uint64_t frames_received;
    uint64_t frames_processed;
    uint64_t frames_invalid;

    uint64_t messages_processed;
    uint64_t messages_unsupported;

    uint64_t events_enqueued;
    uint64_t events_dropped;

    uint64_t bytes_in;
    uint64_t bytes_out;

    uint32_t evq_depth;
    uint32_t inbuf_bytes;
};

#define DRAWFSGIOC_STATS _IOR('D', 0x01, struct drawfs_stats)


struct drawfs_map_surface_req {
    uint32_t surface_id;
};

struct drawfs_map_surface_rep {
    int32_t  status;
    uint32_t surface_id;
    uint32_t stride_bytes;
    uint32_t bytes_total;
};


/*
 * Step 11: select a surface for mmap on this file descriptor.
 * Caller sets surface_id. Kernel fills status, stride_bytes, bytes_total.
 */
struct drawfs_map_surface {
    int32_t  status;
    uint32_t surface_id;
    uint32_t stride_bytes;
    uint32_t bytes_total;
};

#define DRAWFSGIOC_MAP_SURFACE _IOWR('D', 0x02, struct drawfs_map_surface)

#endif
