#ifndef _DEV_DRAWFS_DRAWFS_FRAME_H_
#define _DEV_DRAWFS_DRAWFS_FRAME_H_

#include "drawfs_proto.h"

/*
 * Frame encoding and validation for drawfs protocol.
 *
 * This module handles the low-level wire format:
 * - Validating incoming frame headers
 * - Building outgoing frames with proper alignment
 */

/*
 * Validate a frame header.
 * Returns DRAWFS_ERR_OK on success, error code otherwise.
 * On success, fills out_hdr with the parsed header.
 * On error, fills out_err_offset with the offset of the problematic field.
 */
int drawfs_frame_validate(const uint8_t *buf, size_t n,
    struct drawfs_frame_hdr *out_hdr, uint32_t *out_err_offset);

/*
 * Build a frame containing one message.
 * Allocates and returns the frame buffer, sets *out_len to total frame size.
 * Caller must free the returned buffer with free(buf, M_DRAWFS).
 *
 * Parameters:
 *   frame_id    - unique frame identifier
 *   msg_type    - message type (DRAWFS_RPL_*, DRAWFS_EVT_*)
 *   msg_id      - message ID (echoed from request, or 0 for events)
 *   payload     - message payload bytes (may be NULL if payload_len is 0)
 *   payload_len - payload size in bytes
 *   out_len     - receives total frame size
 *
 * Returns allocated buffer on success, NULL on allocation failure.
 */
uint8_t *drawfs_frame_build(uint32_t frame_id, uint16_t msg_type,
    uint32_t msg_id, const void *payload, size_t payload_len,
    size_t *out_len);

#endif /* _DEV_DRAWFS_DRAWFS_FRAME_H_ */
