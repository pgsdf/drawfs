#ifndef _DEV_DRAWFS_DRAWFS_SURFACE_H_
#define _DEV_DRAWFS_DRAWFS_SURFACE_H_

#include "drawfs_internal.h"

/*
 * Surface lifecycle operations.
 *
 * These functions manage surface objects within a session.
 * Caller is responsible for holding or not holding s->lock as documented.
 */

/*
 * Lookup a surface by ID.
 * Returns the surface pointer or NULL if not found.
 * Acquires and releases s->lock internally.
 */
struct drawfs_surface *drawfs_surface_lookup(struct drawfs_session *s,
    uint32_t surface_id);

/*
 * Create a new surface.
 * Returns 0 on success with surface info in out_*, or an errno on failure.
 * Acquires and releases s->lock internally.
 */
int drawfs_surface_create(struct drawfs_session *s,
    uint32_t width_px, uint32_t height_px, uint32_t format,
    uint32_t *out_surface_id, uint32_t *out_stride_bytes,
    uint32_t *out_bytes_total);

/*
 * Destroy a surface by ID.
 * Returns 0 on success, EINVAL if surface_id is 0, ENOENT if not found.
 * Acquires and releases s->lock internally.
 */
int drawfs_surface_destroy(struct drawfs_session *s, uint32_t surface_id);

/*
 * Select a surface for mmap on this session.
 * Sets s->map_surface_id and returns surface info in out_*.
 * Returns 0 on success, EINVAL if surface_id is 0, ENOENT if not found.
 * Acquires and releases s->lock internally.
 */
int drawfs_surface_select_for_mmap(struct drawfs_session *s,
    uint32_t surface_id, uint32_t *out_stride_bytes, uint32_t *out_bytes_total);

/*
 * Get or allocate the VM object for the currently selected mmap surface.
 * Returns vm_object with reference added on success, NULL on failure.
 * Sets *status_out to 0 on success or an errno on failure.
 * Acquires and releases s->lock internally.
 */
vm_object_t drawfs_surface_get_vmobj(struct drawfs_session *s,
    vm_size_t size, int *status_out);

/*
 * Free all surfaces in a session.
 * Called during session teardown.
 * Caller must ensure no concurrent access (session is closing).
 */
void drawfs_surfaces_free_all(struct drawfs_session *s);

#endif /* _DEV_DRAWFS_DRAWFS_SURFACE_H_ */
