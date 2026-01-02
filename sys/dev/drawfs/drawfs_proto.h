#ifndef _DEV_DRAWFS_DRAWFS_PROTO_H_
#define _DEV_DRAWFS_DRAWFS_PROTO_H_

#include <sys/types.h>

#define DRAWFS_MAGIC   0x31575244u /* 'DRW1' little endian */
#define DRAWFS_VERSION 0x0100u     /* major 1 minor 0 */

#define DRAWFS_ALIGN   4u
static inline uint32_t drawfs_align4(uint32_t n) { return (n + 3u) & ~3u; }

struct drawfs_frame_hdr {
    uint32_t magic;
    uint16_t version;
    uint16_t header_bytes;
    uint32_t frame_bytes;
    uint32_t frame_id;
} __attribute__((packed));

struct drawfs_msg_hdr {
    uint16_t msg_type;
    uint16_t msg_flags;
    uint32_t msg_bytes;
    uint32_t msg_id;
    uint32_t reserved;
} __attribute__((packed));

enum drawfs_msg_type {
    DRAWFS_RPL_OK           = 0x8000,
    DRAWFS_RPL_HELLO        = 0x8001,
    DRAWFS_RPL_DISPLAY_LIST = 0x8010,
    DRAWFS_RPL_DISPLAY_OPEN  = 0x8011,
    DRAWFS_RPL_SURFACE_CREATE = 0x8020,
    DRAWFS_RPL_SURFACE_DESTROY = 0x8021,
    DRAWFS_RPL_SURFACE_PRESENT = 0x8022,
    DRAWFS_RPL_ERROR        = 0x8FFF,

    DRAWFS_REQ_HELLO        = 0x0001,
    DRAWFS_REQ_DISPLAY_LIST = 0x0010,
    DRAWFS_REQ_DISPLAY_OPEN  = 0x0011,
    DRAWFS_REQ_SURFACE_CREATE = 0x0020,
    DRAWFS_REQ_SURFACE_DESTROY = 0x0021,
    DRAWFS_REQ_SURFACE_PRESENT = 0x0022,
};

enum drawfs_err_code {
    DRAWFS_ERR_OK = 0,
    DRAWFS_ERR_INVALID_FRAME = 1,
    DRAWFS_ERR_INVALID_MSG = 2,
    DRAWFS_ERR_UNSUPPORTED_VERSION = 3,
    DRAWFS_ERR_UNSUPPORTED_CAP = 4,
    DRAWFS_ERR_PERMISSION = 5,
    DRAWFS_ERR_NOT_FOUND = 6,
    DRAWFS_ERR_BUSY = 7,
    DRAWFS_ERR_NO_MEMORY = 8,
    DRAWFS_ERR_INVALID_HANDLE = 9,
    DRAWFS_ERR_INVALID_STATE = 10,
    DRAWFS_ERR_INVALID_ARG = 11,
    DRAWFS_ERR_OVERFLOW = 12,
    DRAWFS_ERR_IO = 13,
    DRAWFS_ERR_INTERNAL = 14,
};

struct drawfs_req_hello {
    uint16_t client_major;
    uint16_t client_minor;
    uint32_t client_flags;
    uint32_t max_reply_bytes;
} __attribute__((packed));

struct drawfs_rpl_hello {
    uint16_t server_major;
    uint16_t server_minor;
    uint32_t server_flags;
    uint32_t caps_bytes;
} __attribute__((packed));

struct drawfs_rpl_display_list {
    uint32_t display_count;
} __attribute__((packed));

struct drawfs_rpl_error {
    uint32_t err_code;
    uint32_t err_detail;
    uint32_t err_offset;
} __attribute__((packed));


/*
 * DISPLAY_LIST reply payload (Step 8)
 *
 * Reply message payload layout:
 *   uint32_t count;
 *   struct drawfs_display_desc desc[count];
 *
 * refresh_mhz is millihertz (e.g., 60000 for 60.000 Hz).
 */
struct drawfs_display_desc {
    uint32_t display_id;
    uint32_t width_px;
    uint32_t height_px;
    uint32_t refresh_mhz;
    uint32_t flags; /* reserved */
};


/*
 * DISPLAY_OPEN request payload (Step 9)
 *   uint32_t display_id;
 */
struct drawfs_display_open_req {
    uint32_t display_id;
};

/*
 * DISPLAY_OPEN reply payload (Step 9)
 *   int32_t  status;         (0 = ok, else errno style)
 *   uint32_t display_handle; (0 on failure)
 *   uint32_t active_display_id;
 */
struct drawfs_display_open_rep {
    int32_t  status;
    uint32_t display_handle;
    uint32_t active_display_id;
};


/* Pixel formats (initial) */
enum drawfs_pixel_format {
    DRAWFS_FMT_XRGB8888 = 1,
};

/*
 * SURFACE_CREATE request payload (Step 10A)
 */
struct drawfs_surface_create_req {
    uint32_t width_px;
    uint32_t height_px;
    uint32_t format;
    uint32_t flags;
};

/*
 * SURFACE_CREATE reply payload (Step 10A)
 */
struct drawfs_surface_create_rep {
    int32_t  status;
    uint32_t surface_id;
    uint32_t stride_bytes;
    uint32_t bytes_total;
};


/*
 * SURFACE_DESTROY request payload (Step 10B)
 */
struct drawfs_surface_destroy_req {
    uint32_t surface_id;
};

/*
 * SURFACE_DESTROY reply payload (Step 10B)
 */
struct drawfs_surface_destroy_rep {
    int32_t  status;
    uint32_t surface_id;
};

struct drawfs_surface_present_req {
    uint32_t surface_id;
    uint32_t flags; /* reserved for future (vsync, damage tracking, etc.) */
};

struct drawfs_surface_present_rep {
    int32_t status;
    uint32_t surface_id;
    uint32_t reserved0;
    uint32_t reserved1;
};




/*
 * SURFACE_PRESENT (Step 12)
 */
enum drawfs_event_type {
    DRAWFS_EVT_SURFACE_PRESENTED = 0x9002,
};

struct drawfs_req_surface_present {
    uint32_t surface_id;
    uint32_t flags;
    uint64_t cookie;
} __packed;

struct drawfs_rpl_surface_present {
    int32_t  status;
    uint32_t surface_id;
    uint64_t cookie;
} __packed;

struct drawfs_evt_surface_presented {
    uint32_t surface_id;
    uint32_t reserved;
    uint64_t cookie;
} __packed;
#endif
