/*
 * drawfs_frame.c - Frame encoding and validation for drawfs protocol
 *
 * This module handles the low-level wire format for the drawfs protocol,
 * including frame header validation and frame construction.
 */

#include <sys/param.h>
#include <sys/systm.h>
#include <sys/malloc.h>

#include "drawfs.h"
#include "drawfs_proto.h"
#include "drawfs_internal.h"
#include "drawfs_frame.h"

/*
 * Validate a frame header.
 * Returns DRAWFS_ERR_OK on success, error code otherwise.
 */
int
drawfs_frame_validate(const uint8_t *buf, size_t n,
    struct drawfs_frame_hdr *out_hdr, uint32_t *out_err_offset)
{
    struct drawfs_frame_hdr fh;

    if (n < sizeof(fh)) {
        *out_err_offset = 0;
        return (DRAWFS_ERR_INVALID_FRAME);
    }

    memcpy(&fh, buf, sizeof(fh));

    if (fh.magic != DRAWFS_MAGIC) {
        *out_err_offset = 0;
        return (DRAWFS_ERR_INVALID_FRAME);
    }

    if (fh.version != DRAWFS_VERSION) {
        *out_err_offset = offsetof(struct drawfs_frame_hdr, version);
        return (DRAWFS_ERR_UNSUPPORTED_VERSION);
    }

    if (fh.header_bytes != sizeof(struct drawfs_frame_hdr)) {
        *out_err_offset = offsetof(struct drawfs_frame_hdr, header_bytes);
        return (DRAWFS_ERR_INVALID_FRAME);
    }

    if (fh.frame_bytes < fh.header_bytes) {
        *out_err_offset = offsetof(struct drawfs_frame_hdr, frame_bytes);
        return (DRAWFS_ERR_INVALID_FRAME);
    }

    if (fh.frame_bytes > n) {
        *out_err_offset = offsetof(struct drawfs_frame_hdr, frame_bytes);
        return (DRAWFS_ERR_INVALID_FRAME);
    }

    if ((fh.frame_bytes & 3u) != 0) {
        *out_err_offset = offsetof(struct drawfs_frame_hdr, frame_bytes);
        return (DRAWFS_ERR_INVALID_FRAME);
    }

    *out_hdr = fh;
    *out_err_offset = 0;
    return (DRAWFS_ERR_OK);
}

/*
 * Build a frame containing one message.
 * Returns allocated buffer on success, NULL on failure.
 */
uint8_t *
drawfs_frame_build(uint32_t frame_id, uint16_t msg_type,
    uint32_t msg_id, const void *payload, size_t payload_len,
    size_t *out_len)
{
    struct drawfs_frame_hdr fh;
    struct drawfs_msg_hdr mh;
    uint32_t msg_bytes;
    uint32_t msg_bytes_aligned;
    uint32_t frame_bytes;
    uint8_t *out;

    msg_bytes = (uint32_t)(sizeof(struct drawfs_msg_hdr) + payload_len);
    msg_bytes_aligned = drawfs_align4(msg_bytes);
    frame_bytes = (uint32_t)sizeof(struct drawfs_frame_hdr) + msg_bytes_aligned;

    out = malloc(frame_bytes, M_DRAWFS, M_WAITOK | M_ZERO);
    if (out == NULL) {
        *out_len = 0;
        return (NULL);
    }

    fh.magic = DRAWFS_MAGIC;
    fh.version = DRAWFS_VERSION;
    fh.header_bytes = (uint16_t)sizeof(struct drawfs_frame_hdr);
    fh.frame_bytes = frame_bytes;
    fh.frame_id = frame_id;

    mh.msg_type = msg_type;
    mh.msg_flags = 0;
    mh.msg_bytes = msg_bytes;
    mh.msg_id = msg_id;
    mh.reserved = 0;

    memcpy(out, &fh, sizeof(fh));
    memcpy(out + sizeof(fh), &mh, sizeof(mh));
    if (payload != NULL && payload_len > 0)
        memcpy(out + sizeof(fh) + sizeof(mh), payload, payload_len);

    *out_len = frame_bytes;
    return (out);
}
