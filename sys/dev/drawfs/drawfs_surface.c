/*
 * drawfs_surface.c - Surface lifecycle management for drawfs
 *
 * This module handles creation, destruction, lookup, and mmap support
 * for drawing surfaces within a session.
 *
 * Locking: All functions acquire s->lock internally unless noted otherwise.
 * VM object operations (allocate/deallocate) are done outside the lock to
 * avoid sleeping with mutex held.
 */

#include <sys/param.h>
#include <sys/systm.h>
#include <sys/kernel.h>
#include <sys/malloc.h>
#include <sys/errno.h>
#include <sys/lock.h>
#include <sys/rwlock.h>
#include <sys/pctrie.h>
#include <sys/mutex.h>
#include <machine/atomic.h>
#include <vm/vm.h>
#include <vm/vm_param.h>
#include <vm/vm_page.h>
#include <vm/vm_object.h>
#include <vm/vm_pager.h>

#include "drawfs.h"
#include "drawfs_proto.h"
#include "drawfs_internal.h"
#include "drawfs_surface.h"

/*
 * Lookup a surface by ID.
 * Acquires and releases s->lock internally.
 */
struct drawfs_surface *
drawfs_surface_lookup(struct drawfs_session *s, uint32_t surface_id)
{
    struct drawfs_surface *it;

    mtx_lock(&s->lock);
    TAILQ_FOREACH(it, &s->surfaces, link) {
        if (it->id == surface_id) {
            mtx_unlock(&s->lock);
            return (it);
        }
    }
    mtx_unlock(&s->lock);
    return (NULL);
}

/*
 * Create a new surface.
 * Acquires and releases s->lock internally.
 * Returns 0 on success, or an errno on failure.
 */
int
drawfs_surface_create(struct drawfs_session *s,
    uint32_t width_px, uint32_t height_px, uint32_t format,
    uint32_t *out_surface_id, uint32_t *out_stride_bytes,
    uint32_t *out_bytes_total)
{
    struct drawfs_surface *sf;
    uint64_t stride64, total64;

    *out_surface_id = 0;
    *out_stride_bytes = 0;
    *out_bytes_total = 0;

    /* Must bind a display first. */
    if (s->active_display_id == 0)
        return (EINVAL);

    if (width_px == 0 || height_px == 0)
        return (EINVAL);

    if (format != DRAWFS_FMT_XRGB8888)
        return (EPROTONOSUPPORT);

    /*
     * Step 18 hardening: compute size in 64-bit and clamp.
     * Limits are tunable via hw.drawfs.max_surface_bytes and
     * hw.drawfs.max_session_surface_bytes sysctls.
     */
    stride64 = (uint64_t)width_px * 4ULL;
    total64 = stride64 * (uint64_t)height_px;
    if (stride64 == 0 || total64 == 0 ||
        total64 > (uint64_t)drawfs_max_surface_bytes)
        return (EFBIG);

    /* Allocate surface object. */
    sf = malloc(sizeof(*sf), M_DRAWFS, M_WAITOK | M_ZERO);

    mtx_lock(&s->lock);

    /* Check resource limits (tunable via hw.drawfs.max_surfaces sysctl). */
    if (s->surfaces_count >= (uint32_t)drawfs_max_surfaces ||
        s->surfaces_bytes + total64 > (uint64_t)drawfs_max_session_surface_bytes) {
        mtx_unlock(&s->lock);
        free(sf, M_DRAWFS);
        return (ENOSPC);
    }

    sf->id = s->next_surface_id++;
    sf->width_px = width_px;
    sf->height_px = height_px;
    sf->format = format;
    sf->stride_bytes = (uint32_t)stride64;
    sf->bytes_total = (uint32_t)total64;
    sf->vmobj = NULL;

    TAILQ_INSERT_TAIL(&s->surfaces, sf, link);

    s->surfaces_count++;
    s->surfaces_bytes += total64;

    *out_surface_id = sf->id;
    *out_stride_bytes = sf->stride_bytes;
    *out_bytes_total = sf->bytes_total;

    mtx_unlock(&s->lock);

    return (0);
}

/*
 * Destroy a surface by ID.
 * Acquires s->lock to detach surface; releases before deallocating VM object.
 * Returns 0 on success, EINVAL if surface_id is 0, ENOENT if not found.
 */
int
drawfs_surface_destroy(struct drawfs_session *s, uint32_t surface_id)
{
    struct drawfs_surface *sf;

    if (surface_id == 0)
        return (EINVAL);

    /* Find and detach from session list under lock. */
    sf = NULL;
    mtx_lock(&s->lock);
    TAILQ_FOREACH(sf, &s->surfaces, link) {
        if (sf->id == surface_id)
            break;
    }
    if (sf != NULL) {
        TAILQ_REMOVE(&s->surfaces, sf, link);

        if (s->surfaces_count > 0)
            s->surfaces_count--;
        if (s->surfaces_bytes >= sf->bytes_total)
            s->surfaces_bytes -= sf->bytes_total;
        else
            s->surfaces_bytes = 0;

        /* If this surface was selected for mmap, clear selection. */
        if (s->map_surface_id == sf->id)
            s->map_surface_id = 0;
    }
    mtx_unlock(&s->lock);

    if (sf == NULL)
        return (ENOENT);

    /* Release backing VM object, if any. */
    if (sf->vmobj != NULL) {
        atomic_add_int(&drawfs_vmobj_deallocs, 1);
        vm_object_deallocate(sf->vmobj);
        sf->vmobj = NULL;
    }

    free(sf, M_DRAWFS);
    return (0);
}

/*
 * Select a surface for mmap on this session.
 * Acquires and releases s->lock internally.
 */
int
drawfs_surface_select_for_mmap(struct drawfs_session *s,
    uint32_t surface_id, uint32_t *out_stride_bytes, uint32_t *out_bytes_total)
{
    struct drawfs_surface *sf;

    *out_stride_bytes = 0;
    *out_bytes_total = 0;

    if (surface_id == 0)
        return (EINVAL);

    sf = NULL;
    mtx_lock(&s->lock);
    TAILQ_FOREACH(sf, &s->surfaces, link) {
        if (sf->id == surface_id)
            break;
    }
    if (sf != NULL) {
        s->map_surface_id = surface_id;
        *out_stride_bytes = sf->stride_bytes;
        *out_bytes_total = sf->bytes_total;
    }
    mtx_unlock(&s->lock);

    if (sf == NULL)
        return (ENOENT);

    return (0);
}

/*
 * Get or allocate the VM object for the currently selected mmap surface.
 * Acquires s->lock; may call vm_pager_allocate with lock held (blocking alloc).
 * Returns vm_object with reference added on success, NULL on failure.
 */
vm_object_t
drawfs_surface_get_vmobj(struct drawfs_session *s, vm_size_t size,
    int *status_out)
{
    struct drawfs_surface *sf;
    vm_object_t obj;

    *status_out = 0;
    sf = NULL;

    mtx_lock(&s->lock);

    if (s->map_surface_id != 0) {
        TAILQ_FOREACH(sf, &s->surfaces, link) {
            if (sf->id == s->map_surface_id)
                break;
        }
    }

    if (sf == NULL) {
        mtx_unlock(&s->lock);
        *status_out = ENOENT;
        return (NULL);
    }

    if (size > (vm_size_t)sf->bytes_total) {
        mtx_unlock(&s->lock);
        *status_out = EINVAL;
        return (NULL);
    }

    if (sf->vmobj == NULL) {
        obj = vm_pager_allocate(OBJT_SWAP, NULL, (vm_size_t)sf->bytes_total,
            VM_PROT_DEFAULT, 0, NULL);
        if (obj == NULL) {
            mtx_unlock(&s->lock);
            *status_out = ENOMEM;
            return (NULL);
        }
        sf->vmobj = obj;
        atomic_add_int(&drawfs_vmobj_allocs, 1);
    }

    vm_object_reference(sf->vmobj);
    obj = sf->vmobj;

    mtx_unlock(&s->lock);
    return (obj);
}

/*
 * Free all surfaces in a session.
 * Called during session teardown after s->closing is set.
 * Acquires s->lock briefly per surface; deallocates VM objects outside lock.
 */
void
drawfs_surfaces_free_all(struct drawfs_session *s)
{
    struct drawfs_surface *sf;
    vm_object_t vmobj;

    while ((sf = TAILQ_FIRST(&s->surfaces)) != NULL) {
        TAILQ_REMOVE(&s->surfaces, sf, link);

        /* If this surface is selected for mmap, clear mapping. */
        mtx_lock(&s->lock);
        if (s->map_surface_id == sf->id)
            s->map_surface_id = 0;
        mtx_unlock(&s->lock);

        vmobj = sf->vmobj;
        sf->vmobj = NULL;
        if (vmobj != NULL) {
            atomic_add_int(&drawfs_vmobj_deallocs, 1);
            vm_object_deallocate(vmobj);
        }

        if (s->surfaces_count > 0)
            s->surfaces_count--;
        if (s->surfaces_bytes >= sf->bytes_total)
            s->surfaces_bytes -= sf->bytes_total;
        else
            s->surfaces_bytes = 0;

        free(sf, M_DRAWFS);
    }

    /* Ensure accounting is fully reset. */
    s->surfaces_count = 0;
    s->surfaces_bytes = 0;
}
