/*
 * drawfs.c - FreeBSD character device for graphics protocol
 */

#include <sys/param.h>
#include <sys/systm.h>
#include <sys/kernel.h>
#include <sys/conf.h>
#include <sys/module.h>
#include <sys/malloc.h>
#include <sys/errno.h>
#include <sys/uio.h>
#include <sys/selinfo.h>
#include <sys/lock.h>
#include <sys/mutex.h>
#include <sys/condvar.h>
#include <sys/poll.h>
#include <sys/queue.h>
#include <sys/fcntl.h>
#include <sys/sysctl.h>
#include <vm/vm.h>
#include <vm/vm_object.h>

#include "drawfs.h"
#include "drawfs_proto.h"
#include "drawfs_internal.h"
#include "drawfs_surface.h"
#include "drawfs_frame.h"

MALLOC_DEFINE(M_DRAWFS, "drawfs", "drawfs session and object memory");

/*
 * Sysctl tunable security settings.
 *
 * These can be set via loader.conf (boot-time) or sysctl (runtime for some).
 * Device permissions are only applied at module load time.
 */
static SYSCTL_NODE(_hw, OID_AUTO, drawfs, CTLFLAG_RW | CTLFLAG_MPSAFE, 0,
    "drawfs driver parameters");

static int drawfs_dev_uid = 0;
SYSCTL_INT(_hw_drawfs, OID_AUTO, dev_uid, CTLFLAG_RWTUN,
    &drawfs_dev_uid, 0,
    "Device node owner UID (applied at module load)");

static int drawfs_dev_gid = 0;
SYSCTL_INT(_hw_drawfs, OID_AUTO, dev_gid, CTLFLAG_RWTUN,
    &drawfs_dev_gid, 0,
    "Device node group GID (applied at module load)");

static int drawfs_dev_mode = 0600;
SYSCTL_INT(_hw_drawfs, OID_AUTO, dev_mode, CTLFLAG_RWTUN,
    &drawfs_dev_mode, 0,
    "Device node permissions (applied at module load)");

static int drawfs_mmap_enabled = 1;
SYSCTL_INT(_hw_drawfs, OID_AUTO, mmap_enabled, CTLFLAG_RW,
    &drawfs_mmap_enabled, 0,
    "Allow mmap of surface memory (1=enabled, 0=disabled)");

/*
 * Tunable resource limits.
 *
 * These can be adjusted at runtime via sysctl. Changes take effect for new
 * operations; existing sessions/surfaces are not retroactively affected.
 */
int drawfs_max_evq_bytes = DRAWFS_MAX_EVQ_BYTES;
SYSCTL_INT(_hw_drawfs, OID_AUTO, max_evq_bytes, CTLFLAG_RW,
    &drawfs_max_evq_bytes, 0,
    "Maximum event queue bytes per session (default: 8192)");

int drawfs_max_surfaces = DRAWFS_MAX_SURFACES;
SYSCTL_INT(_hw_drawfs, OID_AUTO, max_surfaces, CTLFLAG_RW,
    &drawfs_max_surfaces, 0,
    "Maximum surfaces per session (default: 64)");

long drawfs_max_surface_bytes = DRAWFS_MAX_SURFACE_BYTES;
SYSCTL_LONG(_hw_drawfs, OID_AUTO, max_surface_bytes, CTLFLAG_RW,
    &drawfs_max_surface_bytes, 0,
    "Maximum bytes per surface (default: 64MB)");

long drawfs_max_session_surface_bytes = DRAWFS_MAX_SESSION_SURFACE_BYTES;
SYSCTL_LONG(_hw_drawfs, OID_AUTO, max_session_surface_bytes, CTLFLAG_RW,
    &drawfs_max_session_surface_bytes, 0,
    "Maximum cumulative surface bytes per session (default: 256MB)");

static int drawfs_coalesce_events = 1;
SYSCTL_INT(_hw_drawfs, OID_AUTO, coalesce_events, CTLFLAG_RW,
    &drawfs_coalesce_events, 0,
    "Coalesce repeated SURFACE_PRESENTED events (1=enabled, 0=disabled)");

/*
 * Debug counters for vm_object lifecycle tracking.
 *
 * These read-only counters track global vm_object allocations and
 * deallocations across all sessions. Useful for detecting leaks:
 * vmobj_allocs - vmobj_deallocs should equal zero after all sessions close.
 */
volatile u_int drawfs_vmobj_allocs = 0;
SYSCTL_UINT(_hw_drawfs, OID_AUTO, vmobj_allocs, CTLFLAG_RD,
    __DEVOLATILE(u_int *, &drawfs_vmobj_allocs), 0,
    "Total vm_object allocations (debug)");

volatile u_int drawfs_vmobj_deallocs = 0;
SYSCTL_UINT(_hw_drawfs, OID_AUTO, vmobj_deallocs, CTLFLAG_RD,
    __DEVOLATILE(u_int *, &drawfs_vmobj_deallocs), 0,
    "Total vm_object deallocations (debug)");

/*
 * Locking model:
 *
 * Each session has a mutex (s->lock) that protects:
 *   - Event queue (evq, evq_bytes)
 *   - Session state (closing flag, active_display_*, map_surface_id)
 *   - Input buffer (inbuf, in_len, in_cap)
 *   - Statistics counters (stats.*)
 *   - Condition variable and select info (cv, sel)
 *
 * Surface list (s->surfaces) is also protected by s->lock. See drawfs_surface.c.
 *
 * Locking rules:
 *   - Never hold s->lock while calling malloc() with M_WAITOK
 *   - Never hold s->lock when calling vm_pager_allocate or vm_object_deallocate
 *   - Callbacks (d_open, d_close, d_read, d_write, d_poll) acquire lock as needed
 *   - Helper functions document whether they acquire lock or expect caller to hold it
 */

static int drawfs_open(struct cdev *dev, int oflags, int devtype, struct thread *td);
static int drawfs_close(struct cdev *dev, int fflag, int devtype, struct thread *td);
static int drawfs_read(struct cdev *dev, struct uio *uio, int ioflag);
static int drawfs_write(struct cdev *dev, struct uio *uio, int ioflag);
static int drawfs_poll(struct cdev *dev, int events, struct thread *td);
static int drawfs_mmap_single(struct cdev *dev, vm_ooffset_t *offset, vm_size_t size, struct vm_object **objp, int nprot);
static int drawfs_ioctl(struct cdev *dev, u_long cmd, caddr_t data, int fflag, struct thread *td);

static void drawfs_session_free(struct drawfs_session *s);
static int drawfs_enqueue_event(struct drawfs_session *s, const void *buf, size_t len);
static int drawfs_try_coalesce_presented(struct drawfs_session *s, uint32_t surface_id, uint64_t new_cookie);

static int drawfs_reply_error(struct drawfs_session *s, uint32_t msg_id, uint32_t err_code, uint32_t err_offset);
static int drawfs_reply_hello(struct drawfs_session *s, uint32_t msg_id);
static int drawfs_reply_display_list(struct drawfs_session *s, uint32_t msg_id);
static int drawfs_reply_display_open(struct drawfs_session *s, uint32_t msg_id, const uint8_t *payload, size_t payload_len);
static int drawfs_reply_surface_create(struct drawfs_session *s, uint32_t msg_id, const uint8_t *payload, size_t payload_len);
static int drawfs_reply_surface_destroy(struct drawfs_session *s, uint32_t msg_id, const uint8_t *payload, size_t payload_len);
static int drawfs_reply_surface_present(struct drawfs_session *s, uint32_t msg_id, const uint8_t *payload, size_t payload_len);

static int drawfs_process_frame(struct drawfs_session *s, const uint8_t *buf, size_t n);

static int drawfs_ingest_bytes(struct drawfs_session *s, const uint8_t *buf, size_t n);
static int drawfs_try_process_inbuf(struct drawfs_session *s);

static int drawfs_send_reply(struct drawfs_session *s, uint16_t msg_type,
    uint32_t msg_id, const void *payload, size_t payload_len);

static struct cdev *drawfs_dev;

static struct cdevsw drawfs_cdevsw = {
    .d_version = D_VERSION,
    .d_open = drawfs_open,
    .d_close = drawfs_close,
    .d_read = drawfs_read,
    .d_write = drawfs_write,
    .d_ioctl = drawfs_ioctl,
    .d_mmap_single = drawfs_mmap_single,
    .d_poll = drawfs_poll,
    .d_name = DRAWFS_DEVNAME,
};

/*
 * Step 11: mmap backing store for a selected surface.
 * Gated by hw.drawfs.mmap_enabled sysctl for security.
 */
static int
drawfs_mmap_single(struct cdev *dev, vm_ooffset_t *offset, vm_size_t size,
    struct vm_object **objp, int nprot)
{
    struct drawfs_session *s;
    vm_object_t obj;
    int status;

    (void)dev;
    (void)nprot;

    /* Check sysctl gate before allowing mmap. */
    if (!drawfs_mmap_enabled)
        return (EPERM);

    if (offset == NULL || objp == NULL)
        return (EINVAL);

    if (*offset != 0)
        return (EINVAL);

    if (size == 0)
        return (EINVAL);

    if (devfs_get_cdevpriv((void **)&s) != 0 || s == NULL)
        return (ENXIO);

    obj = drawfs_surface_get_vmobj(s, size, &status);
    if (obj == NULL)
        return (status);

    *objp = obj;
    return (0);
}

static void
drawfs_priv_dtor(void *data)
{
    struct drawfs_session *s = (struct drawfs_session *)data;
    drawfs_session_free(s);
}

/*
 * Step 10B: SURFACE_DESTROY
 */
static int
drawfs_reply_surface_destroy(struct drawfs_session *s, uint32_t msg_id,
    const uint8_t *payload, size_t payload_len)
{
    struct drawfs_surface_destroy_req req;
    struct drawfs_surface_destroy_rep rep;
    int err;

    rep.status = 0;
    rep.surface_id = 0;

    if (payload_len < sizeof(req)) {
        rep.status = EINVAL;
        goto send_reply;
    }

    memcpy(&req, payload, sizeof(req));
    rep.surface_id = req.surface_id;

    err = drawfs_surface_destroy(s, req.surface_id);
    if (err != 0)
        rep.status = err;

send_reply:
    return drawfs_send_reply(s, DRAWFS_RPL_SURFACE_DESTROY, msg_id, &rep, sizeof(rep));
}

/*
 * Step 12: SURFACE_PRESENT
 */
static int
drawfs_reply_surface_present(struct drawfs_session *s, uint32_t msg_id,
    const uint8_t *payload, size_t payload_len)
{
    struct drawfs_req_surface_present req;
    struct {
        uint32_t surface_id;
        uint64_t cookie;
    } __packed req12;
    struct drawfs_surface *surf;
    struct drawfs_rpl_surface_present rep;
    struct drawfs_evt_surface_presented evt;
    uint32_t surface_id;
    uint64_t cookie;
    int err;

    bzero(&rep, sizeof(rep));
    bzero(&req, sizeof(req));
    bzero(&req12, sizeof(req12));
    surface_id = 0;
    cookie = 0;

    /*
     * Accept two encodings for SURFACE_PRESENT payload:
     *   - 16 bytes: { uint32 surface_id, uint32 rsv, uint64 cookie }
     *   - 12 bytes: { uint32 surface_id, uint64 cookie } (legacy tests)
     */
    if (payload_len >= sizeof(req)) {
        bcopy(payload, &req, sizeof(req));
        surface_id = req.surface_id;
        cookie = req.cookie;
    } else if (payload_len >= sizeof(req12)) {
        bcopy(payload, &req12, sizeof(req12));
        surface_id = req12.surface_id;
        cookie = req12.cookie;
    } else {
        rep.status = EINVAL;
        rep.surface_id = 0;
        rep.cookie = 0;
        goto send_reply;
    }

    if ((s->active_display_id == 0 && s->active_display_handle == 0) || surface_id == 0) {
        rep.status = EINVAL;
        rep.surface_id = 0;
        rep.cookie = cookie;
        goto send_reply;
    }

    surf = drawfs_surface_lookup(s, surface_id);
    if (surf == NULL) {
        rep.status = ENOENT;
        rep.surface_id = 0;
        rep.cookie = cookie;
        goto send_reply;
    }

    /* Success */
    rep.status = 0;
    rep.surface_id = surface_id;
    rep.cookie = cookie;

send_reply:
    err = drawfs_send_reply(s, DRAWFS_RPL_SURFACE_PRESENT, msg_id, &rep, sizeof(rep));
    if (err != 0)
        return (err);

    /* Only emit the async "presented" event on success. */
    if (rep.status != 0)
        return (0);

    evt.surface_id = surface_id;
    evt.reserved = 0;
    evt.cookie = cookie;

    /*
     * Try to coalesce with existing SURFACE_PRESENTED event for same surface.
     * This reduces queue pressure when userland is slow to drain.
     */
    mtx_lock(&s->lock);
    if (drawfs_try_coalesce_presented(s, surface_id, cookie) == 0) {
        mtx_unlock(&s->lock);
        return (0);  /* Coalesced - no new event needed */
    }
    mtx_unlock(&s->lock);

    (void)drawfs_send_reply(s, DRAWFS_EVT_SURFACE_PRESENTED, 0, &evt, sizeof(evt));

    return (0);
}

/*
 * Step 10A: SURFACE_CREATE
 */
static int
drawfs_reply_surface_create(struct drawfs_session *s, uint32_t msg_id,
    const uint8_t *payload, size_t payload_len)
{
    struct drawfs_surface_create_req req;
    struct drawfs_surface_create_rep rep;
    int err;

    rep.status = 0;
    rep.surface_id = 0;
    rep.stride_bytes = 0;
    rep.bytes_total = 0;

    if (payload_len < sizeof(req)) {
        rep.status = EINVAL;
        goto send_reply;
    }

    memcpy(&req, payload, sizeof(req));

    err = drawfs_surface_create(s, req.width_px, req.height_px, req.format,
        &rep.surface_id, &rep.stride_bytes, &rep.bytes_total);
    if (err != 0)
        rep.status = err;

send_reply:
    return drawfs_send_reply(s, DRAWFS_RPL_SURFACE_CREATE, msg_id, &rep, sizeof(rep));
}

static int
drawfs_reply_display_open(struct drawfs_session *s, uint32_t msg_id, const uint8_t *payload, size_t payload_len)
{
    struct drawfs_display_open_req req;
    struct drawfs_display_open_rep rep;

    rep.status = 0;
    rep.display_handle = 0;
    rep.active_display_id = 0;

    if (payload_len < sizeof(req)) {
        rep.status = EINVAL;
        goto send_reply;
    }

    memcpy(&req, payload, sizeof(req));

    /* Validate display_id against current stub list (Step 8). */
    if (req.display_id != 1) {
        rep.status = ENODEV;
        goto send_reply;
    }

    /* Bind session to display. */
    mtx_lock(&s->lock);
    s->active_display_id = req.display_id;
    if (s->active_display_handle == 0)
        s->active_display_handle = s->next_display_handle++;
    rep.display_handle = s->active_display_handle;
    rep.active_display_id = s->active_display_id;
    mtx_unlock(&s->lock);

send_reply:
    return drawfs_send_reply(s, DRAWFS_RPL_DISPLAY_OPEN, msg_id, &rep, sizeof(rep));
}

static int
drawfs_open(struct cdev *dev, int oflags, int devtype, struct thread *td)
{
    struct drawfs_session *s;

    (void)dev;
    (void)oflags;
    (void)devtype;
    (void)td;

    s = malloc(sizeof(*s), M_DRAWFS, M_WAITOK | M_ZERO);
    mtx_init(&s->lock, "drawfs_session", NULL, MTX_DEF);
    cv_init(&s->cv, "drawfs_cv");
    TAILQ_INIT(&s->evq);
    TAILQ_INIT(&s->surfaces);

    s->active_display_id = 0;
    s->active_display_handle = 0;
    s->next_display_handle = 1;
    s->next_surface_id = 1;

    s->closing = false;
    s->evq_bytes = 0;
    s->next_out_frame_id = 1;

    s->in_cap = 4096;
    s->inbuf = malloc(s->in_cap, M_DRAWFS, M_WAITOK | M_ZERO);
    s->in_len = 0;

    return (devfs_set_cdevpriv(s, drawfs_priv_dtor));
}

static int
drawfs_close(struct cdev *dev, int fflag, int devtype, struct thread *td)
{
    (void)dev;
    (void)fflag;
    (void)devtype;
    (void)td;
    return (0);
}

static int
drawfs_read(struct cdev *dev, struct uio *uio, int ioflag)
{
    struct drawfs_session *s;
    struct drawfs_event *ev;
    int error;

    (void)dev;

    error = devfs_get_cdevpriv((void **)&s);
    if (error != 0)
        return (error);

    mtx_lock(&s->lock);

    for (;;) {
        if (s->closing) {
            mtx_unlock(&s->lock);
            return (ENXIO);
        }

        if (!TAILQ_EMPTY(&s->evq))
            break;

        if ((ioflag & O_NONBLOCK) != 0) {
            mtx_unlock(&s->lock);
            return (EWOULDBLOCK);
        }

        error = cv_wait_sig(&s->cv, &s->lock);
        if (error != 0) {
            mtx_unlock(&s->lock);
            return (error);
        }
    }

    ev = TAILQ_FIRST(&s->evq);
    TAILQ_REMOVE(&s->evq, ev, link);
    s->evq_bytes -= ev->len;

    mtx_unlock(&s->lock);

    error = uiomove(ev->bytes, (int)ev->len, uio);

    free(ev->bytes, M_DRAWFS);
    free(ev, M_DRAWFS);

    return (error);
}

static int
drawfs_write(struct cdev *dev, struct uio *uio, int ioflag)
{
    struct drawfs_session *s;
    int error;
    size_t n;
    uint8_t *buf;

    (void)dev;
    (void)ioflag;

    error = devfs_get_cdevpriv((void **)&s);
    if (error != 0)
        return (error);

    n = uio->uio_resid;
    if (n == 0)
        return (0);

    if (n > DRAWFS_MAX_FRAME_BYTES)
        return (EFBIG);

    buf = malloc(n, M_DRAWFS, M_WAITOK);
    error = uiomove(buf, (int)n, uio);
    if (error != 0) {
        free(buf, M_DRAWFS);
        return (error);
    }

    s->stats.bytes_in += (uint64_t)n;
    error = drawfs_ingest_bytes(s, buf, n);

    free(buf, M_DRAWFS);
    return (error);
}

static int
drawfs_poll(struct cdev *dev, int events, struct thread *td)
{
    struct drawfs_session *s;
    int error;
    int revents;

    (void)dev;

    error = devfs_get_cdevpriv((void **)&s);
    if (error != 0)
        return (events & (POLLERR | POLLHUP));

    revents = 0;

    mtx_lock(&s->lock);

    if (s->closing) {
        revents |= (events & (POLLHUP | POLLERR)) ? (events & (POLLHUP | POLLERR)) : POLLHUP;
        mtx_unlock(&s->lock);
        return (revents);
    }

    if ((events & (POLLIN | POLLRDNORM)) != 0) {
        if (!TAILQ_EMPTY(&s->evq))
            revents |= events & (POLLIN | POLLRDNORM);
        else
            selrecord(td, &s->sel);
    }

    mtx_unlock(&s->lock);

    return (revents);
}

static int
drawfs_ioctl(struct cdev *dev, u_long cmd, caddr_t data, int fflag, struct thread *td)
{
    struct drawfs_session *s;
    int error;

    (void)dev;
    (void)fflag;
    (void)td;

    error = devfs_get_cdevpriv((void **)&s);
    if (error != 0)
        return (error);

    switch (cmd) {

    case DRAWFSGIOC_MAP_SURFACE: {
        struct drawfs_map_surface *ms;
        int err;

        ms = (struct drawfs_map_surface *)data;
        ms->status = 0;
        ms->stride_bytes = 0;
        ms->bytes_total = 0;

        err = drawfs_surface_select_for_mmap(s, ms->surface_id,
            &ms->stride_bytes, &ms->bytes_total);
        if (err != 0)
            ms->status = err;

        break;
    }

    case DRAWFSGIOC_STATS: {
        struct drawfs_stats *out = (struct drawfs_stats *)data;

        mtx_lock(&s->lock);

        *out = s->stats;

        out->inbuf_bytes = (uint32_t)s->in_len;

        uint32_t depth = 0;
        struct drawfs_event *ev;
        TAILQ_FOREACH(ev, &s->evq, link) {
            depth++;
        }
        out->evq_depth = depth;

        /* Observability: current resource usage */
        out->evq_bytes = (uint32_t)s->evq_bytes;
        out->surfaces_count = s->surfaces_count;
        out->surfaces_bytes = s->surfaces_bytes;

        mtx_unlock(&s->lock);
        return (0);
    }

    default:
        return (ENOTTY);
    }

    return (0);
}

/*
 * Free all session resources.
 * Acquires s->lock to set closing flag and drain queues; releases before
 * destroying surfaces (which may sleep on VM object deallocation).
 */
static void
drawfs_session_free(struct drawfs_session *s)
{
    struct drawfs_event *ev, *tmp;

    if (s == NULL)
        return;

    mtx_lock(&s->lock);
    s->closing = true;

    cv_broadcast(&s->cv);
    selwakeup(&s->sel);

    TAILQ_FOREACH_SAFE(ev, &s->evq, link, tmp) {
        TAILQ_REMOVE(&s->evq, ev, link);
        free(ev->bytes, M_DRAWFS);
        free(ev, M_DRAWFS);
    }
    s->evq_bytes = 0;

    if (s->inbuf != NULL) {
        free(s->inbuf, M_DRAWFS);
        s->inbuf = NULL;
        s->in_len = 0;
        s->in_cap = 0;
    }

    mtx_unlock(&s->lock);

    /* Free all surfaces (uses its own locking). */
    drawfs_surfaces_free_all(s);

    seldrain(&s->sel);
    cv_destroy(&s->cv);
    mtx_destroy(&s->lock);
    free(s, M_DRAWFS);
}

/*
 * Try to coalesce a SURFACE_PRESENTED event with an existing one in the queue.
 * Must be called with s->lock held.
 * Returns 0 if coalesced (caller should not enqueue new event), ENOENT otherwise.
 */
static int
drawfs_try_coalesce_presented(struct drawfs_session *s, uint32_t surface_id,
    uint64_t new_cookie)
{
    struct drawfs_event *ev;
    struct drawfs_msg_hdr mh;
    uint32_t ev_surface_id;
    size_t payload_off;

    if (!drawfs_coalesce_events)
        return (ENOENT);

    /*
     * Search queue for existing SURFACE_PRESENTED event for same surface.
     * Frame format: frame_hdr(16) + msg_hdr(16) + payload(16)
     * Payload: surface_id(4) + reserved(4) + cookie(8)
     */
    TAILQ_FOREACH(ev, &s->evq, link) {
        if (ev->len < sizeof(struct drawfs_frame_hdr) +
            sizeof(struct drawfs_msg_hdr) + 16)
            continue;

        /* Check msg_type at offset 16 */
        memcpy(&mh, ev->bytes + sizeof(struct drawfs_frame_hdr),
            sizeof(mh));
        if (mh.msg_type != DRAWFS_EVT_SURFACE_PRESENTED)
            continue;

        /* Check surface_id at offset 32 */
        payload_off = sizeof(struct drawfs_frame_hdr) +
            sizeof(struct drawfs_msg_hdr);
        memcpy(&ev_surface_id, ev->bytes + payload_off, sizeof(uint32_t));
        if (ev_surface_id != surface_id)
            continue;

        /* Found match - update cookie at offset 40 (payload_off + 8) */
        memcpy(ev->bytes + payload_off + 8, &new_cookie, sizeof(uint64_t));
        return (0);
    }

    return (ENOENT);
}

/*
 * Enqueue an event (frame) to the session's read queue.
 * Acquires and releases s->lock internally.
 */
static int
drawfs_enqueue_event(struct drawfs_session *s, const void *buf, size_t len)
{
    struct drawfs_event *ev;

    if (len == 0)
        return (0);

    if (len > DRAWFS_MAX_EVENT_BYTES)
        return (EFBIG);

    ev = malloc(sizeof(*ev), M_DRAWFS, M_WAITOK | M_ZERO);
    ev->bytes = malloc(len, M_DRAWFS, M_WAITOK);
    ev->len = len;
    memcpy(ev->bytes, buf, len);

    mtx_lock(&s->lock);

    /*
     * Step 19: event queue backpressure.
     * Limit is tunable via hw.drawfs.max_evq_bytes sysctl.
     */
    if (s->evq_bytes + len > (size_t)drawfs_max_evq_bytes) {
        s->stats.events_dropped++;
        mtx_unlock(&s->lock);
        free(ev->bytes, M_DRAWFS);
        free(ev, M_DRAWFS);
        return (ENOSPC);
    }

    if (s->closing) {
        s->stats.events_dropped++;
        mtx_unlock(&s->lock);
        free(ev->bytes, M_DRAWFS);
        free(ev, M_DRAWFS);
        return (ENXIO);
    }

    TAILQ_INSERT_TAIL(&s->evq, ev, link);
    s->evq_bytes += len;

    s->stats.events_enqueued++;
    s->stats.bytes_out += (uint64_t)len;

    cv_signal(&s->cv);
    selwakeup(&s->sel);

    mtx_unlock(&s->lock);

    return (0);
}

/*
 * Append incoming bytes to session's input buffer and try to process.
 * Acquires and releases s->lock internally.
 */
static int
drawfs_ingest_bytes(struct drawfs_session *s, const uint8_t *buf, size_t n)
{
    if (n == 0)
        return (0);

    if (n > DRAWFS_MAX_FRAME_BYTES)
        return (EFBIG);

    mtx_lock(&s->lock);

    if (s->closing) {
        mtx_unlock(&s->lock);
        return (ENXIO);
    }

    size_t need = s->in_len + n;
    if (need > DRAWFS_MAX_FRAME_BYTES) {
        s->in_len = 0;
        mtx_unlock(&s->lock);
        (void)drawfs_reply_error(s, 0, DRAWFS_ERR_OVERFLOW, 0);
        return (0);
    }

    if (need > s->in_cap) {
        size_t newcap = s->in_cap;
        while (newcap < need)
            newcap *= 2;
        if (newcap > DRAWFS_MAX_FRAME_BYTES)
            newcap = DRAWFS_MAX_FRAME_BYTES;

        uint8_t *nb = malloc(newcap, M_DRAWFS, M_WAITOK);
        memcpy(nb, s->inbuf, s->in_len);
        free(s->inbuf, M_DRAWFS);
        s->inbuf = nb;
        s->in_cap = newcap;
    }

    memcpy(s->inbuf + s->in_len, buf, n);
    s->in_len += n;

    mtx_unlock(&s->lock);

    return drawfs_try_process_inbuf(s);
}

/*
 * Try to process complete frames from the input buffer.
 * Acquires s->lock for each iteration; releases before calling process_frame.
 */
static int
drawfs_try_process_inbuf(struct drawfs_session *s)
{
    for (;;) {
        struct drawfs_frame_hdr fh;
        uint32_t err_off;
        int v;
        size_t frame_bytes;

        mtx_lock(&s->lock);

        if (s->closing) {
            mtx_unlock(&s->lock);
            return (ENXIO);
        }

        if (s->in_len < sizeof(struct drawfs_frame_hdr)) {
            mtx_unlock(&s->lock);
            return (0);
        }

        memcpy(&fh, s->inbuf, sizeof(fh));
        s->stats.frames_received += 1;

        if (fh.magic != DRAWFS_MAGIC) {
            s->stats.frames_invalid += 1;
            s->in_len = 0;
            mtx_unlock(&s->lock);
            (void)drawfs_reply_error(s, 0, DRAWFS_ERR_INVALID_FRAME, 0);
            return (0);
        }

        if (fh.header_bytes != sizeof(struct drawfs_frame_hdr)) {
            s->in_len = 0;
            mtx_unlock(&s->lock);
            (void)drawfs_reply_error(s, 0, DRAWFS_ERR_INVALID_FRAME, offsetof(struct drawfs_frame_hdr, header_bytes));
            return (0);
        }

        frame_bytes = fh.frame_bytes;

        if (frame_bytes == 0 || frame_bytes > DRAWFS_MAX_FRAME_BYTES || (frame_bytes & 3u) != 0) {
            s->in_len = 0;
            mtx_unlock(&s->lock);
            (void)drawfs_reply_error(s, 0, DRAWFS_ERR_INVALID_FRAME, offsetof(struct drawfs_frame_hdr, frame_bytes));
            return (0);
        }

        if (s->in_len < frame_bytes) {
            mtx_unlock(&s->lock);
            return (0);
        }

        uint8_t *frame = malloc(frame_bytes, M_DRAWFS, M_WAITOK);
        memcpy(frame, s->inbuf, frame_bytes);

        size_t remain = s->in_len - frame_bytes;
        if (remain > 0)
            memmove(s->inbuf, s->inbuf + frame_bytes, remain);
        s->in_len = remain;

        mtx_unlock(&s->lock);

        v = drawfs_frame_validate(frame, frame_bytes, &fh, &err_off);
        if (v != DRAWFS_ERR_OK) {
            s->stats.frames_invalid += 1;
            (void)drawfs_reply_error(s, 0, (uint32_t)v, err_off);
            free(frame, M_DRAWFS);
            continue;
        }

        v = drawfs_process_frame(s, frame, frame_bytes);
        s->stats.frames_processed += 1;
        free(frame, M_DRAWFS);

        /* Propagate backpressure errors to write() caller */
        if (v != 0)
            return (v);
    }
}

static int
drawfs_process_frame(struct drawfs_session *s, const uint8_t *buf, size_t n)
{
    struct drawfs_frame_hdr fh;
    uint32_t err_off;
    int v;

    v = drawfs_frame_validate(buf, n, &fh, &err_off);
    if (v != DRAWFS_ERR_OK) {
        (void)drawfs_reply_error(s, 0, (uint32_t)v, err_off);
        return (0);
    }

    uint32_t pos = (uint32_t)sizeof(struct drawfs_frame_hdr);
    uint32_t end = fh.frame_bytes;

    while (pos + sizeof(struct drawfs_msg_hdr) <= end) {
        struct drawfs_msg_hdr mh;
        memcpy(&mh, buf + pos, sizeof(mh));

        if (mh.msg_bytes < sizeof(struct drawfs_msg_hdr)) {
            (void)drawfs_reply_error(s, mh.msg_id, DRAWFS_ERR_INVALID_MSG, pos);
            return (0);
        }
        if (mh.msg_bytes > DRAWFS_MAX_MSG_BYTES) {
            (void)drawfs_reply_error(s, mh.msg_id, DRAWFS_ERR_INVALID_MSG, pos);
            return (0);
        }

        uint32_t msg_end = pos + mh.msg_bytes;
        if (msg_end > end) {
            (void)drawfs_reply_error(s, mh.msg_id, DRAWFS_ERR_INVALID_MSG, pos);
            return (0);
        }

        const uint8_t *payload = buf + pos + sizeof(struct drawfs_msg_hdr);
        uint32_t payload_len = mh.msg_bytes - (uint32_t)sizeof(struct drawfs_msg_hdr);

        (void)payload;

        s->stats.messages_processed += 1;

        switch (mh.msg_type) {
        case DRAWFS_REQ_HELLO:
            if (payload_len < sizeof(struct drawfs_req_hello)) {
                (void)drawfs_reply_error(s, mh.msg_id, DRAWFS_ERR_INVALID_ARG, pos);
                break;
            }
            (void)drawfs_reply_hello(s, mh.msg_id);
            break;

        case DRAWFS_REQ_DISPLAY_LIST:
            (void)drawfs_reply_display_list(s, mh.msg_id);
            break;

        case DRAWFS_REQ_DISPLAY_OPEN:
            (void)drawfs_reply_display_open(s, mh.msg_id, payload, payload_len);
            break;

        case DRAWFS_REQ_SURFACE_CREATE:
            (void)drawfs_reply_surface_create(s, mh.msg_id, payload, payload_len);
            break;

        case DRAWFS_REQ_SURFACE_DESTROY:
            (void)drawfs_reply_surface_destroy(s, mh.msg_id, payload, payload_len);
            break;

        case DRAWFS_REQ_SURFACE_PRESENT: {
            int error;

            error = drawfs_reply_surface_present(s, mh.msg_id, payload, payload_len);
            if (error != 0)
                return (error);
            break;
        }

        default:
            s->stats.messages_unsupported += 1;
            (void)drawfs_reply_error(s, mh.msg_id, DRAWFS_ERR_UNSUPPORTED_CAP, pos);
            break;
        }

        pos = drawfs_align4(msg_end);
    }

    return (0);
}

/*
 * Build and enqueue a reply frame.
 * Does not hold s->lock; calls drawfs_enqueue_event which acquires it.
 */
static int
drawfs_send_reply(struct drawfs_session *s, uint16_t msg_type,
    uint32_t msg_id, const void *payload, size_t payload_len)
{
    uint8_t *frame;
    size_t frame_len;
    int err;

    frame = drawfs_frame_build(s->next_out_frame_id++, msg_type, msg_id,
        payload, payload_len, &frame_len);

    err = drawfs_enqueue_event(s, frame, frame_len);
    free(frame, M_DRAWFS);
    return (err);
}

static int
drawfs_reply_error(struct drawfs_session *s, uint32_t msg_id, uint32_t err_code, uint32_t err_offset)
{
    struct drawfs_rpl_error ep;

    ep.err_code = err_code;
    ep.err_detail = 0;
    ep.err_offset = err_offset;

    return drawfs_send_reply(s, DRAWFS_RPL_ERROR, msg_id, &ep, sizeof(ep));
}

static int
drawfs_reply_hello(struct drawfs_session *s, uint32_t msg_id)
{
    struct drawfs_rpl_hello hp;

    hp.status = 0;
    hp.server_major = 1;
    hp.server_minor = 0;
    hp.server_flags = 0;
    hp.max_reply_bytes = 0;

    return drawfs_send_reply(s, DRAWFS_RPL_HELLO, msg_id, &hp, sizeof(hp));
}

static int
drawfs_reply_display_list(struct drawfs_session *s, uint32_t msg_id)
{
    struct {
        int32_t  status;
        uint32_t count;
        struct drawfs_display_desc desc;
    } payload;

    payload.status = 0;
    payload.count = 1;
    payload.desc.display_id = 1;
    payload.desc.width_px = 1920;
    payload.desc.height_px = 1080;
    payload.desc.refresh_mhz = 60000;
    payload.desc.flags = 0;

    return drawfs_send_reply(s, DRAWFS_RPL_DISPLAY_LIST, msg_id,
        &payload, sizeof(payload));
}

static int
drawfs_modevent(module_t mod, int type, void *data)
{
    int error;

    (void)mod;
    (void)data;
    error = 0;

    switch (type) {
    case MOD_LOAD:
        drawfs_dev = make_dev(&drawfs_cdevsw, 0,
            (uid_t)drawfs_dev_uid,
            (gid_t)drawfs_dev_gid,
            drawfs_dev_mode,
            DRAWFS_DEVNAME);
        uprintf("drawfs loaded, device %s created (uid=%d gid=%d mode=%04o)\n",
            DRAWFS_NODEPATH, drawfs_dev_uid, drawfs_dev_gid, drawfs_dev_mode);
        break;

    case MOD_UNLOAD:
        if (drawfs_dev != NULL)
            destroy_dev(drawfs_dev);
        uprintf("drawfs unloaded\n");
        break;

    default:
        error = EOPNOTSUPP;
        break;
    }

    return (error);
}

DEV_MODULE(drawfs, drawfs_modevent, NULL);
MODULE_VERSION(drawfs, 1);
