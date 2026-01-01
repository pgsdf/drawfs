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
#include <sys/rwlock.h>
#include <sys/pctrie.h>
#include <vm/vm.h>
#include <vm/vm_param.h>
#include <vm/vm_page.h>
#include <vm/vm_object.h>
#include <vm/vm_pager.h>
#include <sys/poll.h>
#include <sys/queue.h>
#include <sys/lock.h>
#include <sys/mutex.h>
#include <sys/condvar.h>
#include <sys/fcntl.h>

#include "drawfs.h"
#include "drawfs_proto.h"
#include "drawfs_ioctl.h"

MALLOC_DEFINE(M_DRAWFS, "drawfs", "drawfs session and object memory");

struct drawfs_event {
    TAILQ_ENTRY(drawfs_event) link;
    size_t len;
    uint8_t *bytes;
};

struct drawfs_surface {
    TAILQ_ENTRY(drawfs_surface) link;
    uint32_t id;
    uint32_t width_px;
    uint32_t height_px;
    uint32_t format;
    uint32_t stride_bytes;
    uint32_t bytes_total;
    vm_object_t vmobj;
    int vmobj_refs;
};

TAILQ_HEAD(drawfs_surface_list, drawfs_surface);
TAILQ_HEAD(drawfs_eventq, drawfs_event);

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
    uint32_t next_display_handle;
    uint32_t active_display_handle;

    /* Surface objects (Step 10A) */
    struct drawfs_surface_list surfaces;
    uint32_t next_surface_id;

    /* Stats (per session) */
    struct drawfs_stats stats;
};

static int drawfs_open(struct cdev *dev, int oflags, int devtype, struct thread *td);
static int drawfs_close(struct cdev *dev, int fflag, int devtype, struct thread *td);
static int drawfs_read(struct cdev *dev, struct uio *uio, int ioflag);
static int drawfs_write(struct cdev *dev, struct uio *uio, int ioflag);
static int drawfs_poll(struct cdev *dev, int events, struct thread *td);
static int drawfs_mmap_single(struct cdev *dev, vm_ooffset_t *offset, vm_size_t size, struct vm_object **objp, int nprot);
/*
 * Step 11: mmap backing store for a selected surface.
 *
 * The selection is per file descriptor:
 * 1) user calls DRAWFSGIOC_MAP_SURFACE with surface_id
 * 2) user mmaps /dev/draw with offset 0 and size <= bytes_total
 *
 * We return a swap backed vm_object sized to bytes_total.
 */
static int
drawfs_mmap_single(struct cdev *dev, vm_ooffset_t *offset, vm_size_t size,
    struct vm_object **objp, int nprot)
{
    struct drawfs_session *s;
    struct drawfs_surface *sf;
    vm_object_t obj;

    (void)nprot;

    if (offset == NULL || objp == NULL)
        return (EINVAL);

    if (*offset != 0)
        return (EINVAL);

    if (size == 0)
        return (EINVAL);
    /* Per-file-descriptor session */
    if (devfs_get_cdevpriv((void **)&s) != 0 || s == NULL)
        return (ENXIO);

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
        return (ENOENT);
    }

    if (size > (vm_size_t)sf->bytes_total) {
        mtx_unlock(&s->lock);
        return (EINVAL);
    }

    if (sf->vmobj == NULL) {
        obj = vm_pager_allocate(OBJT_SWAP, NULL, (vm_size_t)sf->bytes_total,
            VM_PROT_DEFAULT, 0, NULL);
        if (obj == NULL) {
            mtx_unlock(&s->lock);
            return (ENOMEM);
        }
        sf->vmobj = obj;
    }

    vm_object_reference(sf->vmobj);
    *objp = sf->vmobj;

    mtx_unlock(&s->lock);
    return (0);
}


static int drawfs_ioctl(struct cdev *dev, u_long cmd, caddr_t data, int fflag, struct thread *td);

static void drawfs_session_free(struct drawfs_session *s);
static int drawfs_enqueue_event(struct drawfs_session *s, const void *buf, size_t len);

static int drawfs_reply_ok(struct drawfs_session *s, uint32_t msg_id);
static int drawfs_reply_error(struct drawfs_session *s, uint32_t msg_id, uint32_t err_code, uint32_t err_offset);
static int drawfs_reply_hello(struct drawfs_session *s, uint32_t msg_id);
static int drawfs_reply_display_list(struct drawfs_session *s, uint32_t msg_id);
static int drawfs_reply_display_open(struct drawfs_session *s, uint32_t msg_id, const uint8_t *payload, size_t payload_len);
static int drawfs_reply_surface_create(struct drawfs_session *s, uint32_t msg_id, const uint8_t *payload, size_t payload_len);
static int drawfs_reply_surface_destroy(struct drawfs_session *s, uint32_t msg_id, const uint8_t *payload, size_t payload_len);
static void drawfs_free_surfaces(struct drawfs_session *s);

static int drawfs_validate_frame(const uint8_t *buf, size_t n, struct drawfs_frame_hdr *out_hdr, uint32_t *out_err_offset);
static int drawfs_process_frame(struct drawfs_session *s, const uint8_t *buf, size_t n);

static int drawfs_ingest_bytes(struct drawfs_session *s, const uint8_t *buf, size_t n);
static int drawfs_try_process_inbuf(struct drawfs_session *s);

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
    struct drawfs_surface *sf;

    rep.status = 0;
    rep.surface_id = 0;

    if (payload_len < sizeof(req)) {
        rep.status = EINVAL;
        goto build_reply;
    }

    memcpy(&req, payload, sizeof(req));
    rep.surface_id = req.surface_id;

    if (req.surface_id == 0) {
        rep.status = EINVAL;
        goto build_reply;
    }

    sf = NULL;
    mtx_lock(&s->lock);
    TAILQ_FOREACH(sf, &s->surfaces, link) {
        if (sf->id == req.surface_id)
            break;
    }
    if (sf != NULL)
        TAILQ_REMOVE(&s->surfaces, sf, link);
    mtx_unlock(&s->lock);

    if (sf == NULL) {
        rep.status = ENOENT;
        goto build_reply;
    }

    free(sf, M_DRAWFS);

build_reply:
    {
        uint32_t payload_bytes;
        uint32_t msg_bytes;
        uint32_t msg_bytes_aligned;
        uint32_t frame_bytes;

        uint8_t *out;
        struct drawfs_frame_hdr fh;
        struct drawfs_msg_hdr mh;

        payload_bytes = (uint32_t)sizeof(rep);
        msg_bytes = (uint32_t)sizeof(struct drawfs_msg_hdr) + payload_bytes;
        msg_bytes_aligned = drawfs_align4(msg_bytes);
        frame_bytes = (uint32_t)sizeof(struct drawfs_frame_hdr) + msg_bytes_aligned;

        out = malloc(frame_bytes, M_DRAWFS, M_WAITOK | M_ZERO);

        fh.magic = DRAWFS_MAGIC;
        fh.version = DRAWFS_VERSION;
        fh.header_bytes = (uint16_t)sizeof(struct drawfs_frame_hdr);
        fh.frame_bytes = frame_bytes;
        fh.frame_id = s->next_out_frame_id++;

        mh.msg_type = DRAWFS_RPL_SURFACE_DESTROY;
        mh.msg_flags = 0;
        mh.msg_bytes = msg_bytes;
        mh.msg_id = msg_id;
        mh.reserved = 0;

        memcpy(out, &fh, sizeof(fh));
        memcpy(out + sizeof(fh), &mh, sizeof(mh));
        memcpy(out + sizeof(fh) + sizeof(mh), &rep, sizeof(rep));

        int err = drawfs_enqueue_event(s, out, frame_bytes);
        free(out, M_DRAWFS);
        return (err);
    }
}

/*
 * Step 10A: SURFACE_CREATE
 * This is a semantic object only. No buffer mapping yet.
 */
static int
drawfs_reply_surface_create(struct drawfs_session *s, uint32_t msg_id,
    const uint8_t *payload, size_t payload_len)
{
    struct drawfs_surface_create_req req;
    struct drawfs_surface_create_rep rep;
    struct drawfs_surface *sf;

    rep.status = 0;
    rep.surface_id = 0;
    rep.stride_bytes = 0;
    rep.bytes_total = 0;

    sf = NULL;

    /* Must bind a display first. */
    if (s->active_display_id == 0) {
        rep.status = EINVAL;
        goto build_reply;
    }

    if (payload_len < sizeof(req)) {
        rep.status = EINVAL;
        goto build_reply;
    }

    memcpy(&req, payload, sizeof(req));

    if (req.width_px == 0 || req.height_px == 0) {
        rep.status = EINVAL;
        goto build_reply;
    }

    if (req.format != DRAWFS_FMT_XRGB8888) {
        rep.status = EPROTONOSUPPORT;
        goto build_reply;
    }

    /* Allocate and record a semantic surface object. */
    sf = malloc(sizeof(*sf), M_DRAWFS, M_WAITOK | M_ZERO);

    mtx_lock(&s->lock);
    sf->id = s->next_surface_id++;
    sf->width_px = req.width_px;
    sf->height_px = req.height_px;
    sf->format = req.format;
    sf->stride_bytes = req.width_px * 4;
    sf->bytes_total = sf->stride_bytes * req.height_px;

    TAILQ_INSERT_TAIL(&s->surfaces, sf, link);

    rep.surface_id = sf->id;
    rep.stride_bytes = sf->stride_bytes;
    rep.bytes_total = sf->bytes_total;
    mtx_unlock(&s->lock);

build_reply:
    {
        uint32_t payload_bytes;
        uint32_t msg_bytes;
        uint32_t msg_bytes_aligned;
        uint32_t frame_bytes;

        uint8_t *out;
        struct drawfs_frame_hdr fh;
        struct drawfs_msg_hdr mh;

        payload_bytes = (uint32_t)sizeof(rep);
        msg_bytes = (uint32_t)sizeof(struct drawfs_msg_hdr) + payload_bytes;
        msg_bytes_aligned = drawfs_align4(msg_bytes);
        frame_bytes = (uint32_t)sizeof(struct drawfs_frame_hdr) + msg_bytes_aligned;

        out = malloc(frame_bytes, M_DRAWFS, M_WAITOK | M_ZERO);

        fh.magic = DRAWFS_MAGIC;
        fh.version = DRAWFS_VERSION;
        fh.header_bytes = (uint16_t)sizeof(struct drawfs_frame_hdr);
        fh.frame_bytes = frame_bytes;
        fh.frame_id = s->next_out_frame_id++;

        mh.msg_type = DRAWFS_RPL_SURFACE_CREATE;
        mh.msg_flags = 0;
        mh.msg_bytes = msg_bytes;
        mh.msg_id = msg_id;
        mh.reserved = 0;

        memcpy(out, &fh, sizeof(fh));
        memcpy(out + sizeof(fh), &mh, sizeof(mh));
        memcpy(out + sizeof(fh) + sizeof(mh), &rep, sizeof(rep));

        int err = drawfs_enqueue_event(s, out, frame_bytes);
        free(out, M_DRAWFS);
        return (err);
    }
}

static void
drawfs_free_surfaces(struct drawfs_session *s)
{
    struct drawfs_surface *sf, *tmp;

    TAILQ_FOREACH_SAFE(sf, &s->surfaces, link, tmp) {
        TAILQ_REMOVE(&s->surfaces, sf, link);
        free(sf, M_DRAWFS);
    }
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
        /* fallthrough to reply build */
        goto build_reply;
    }

    memcpy(&req, payload, sizeof(req));

    /* Validate display_id against current stub list (Step 8). */
    if (req.display_id != 1) {
        rep.status = ENODEV;
        goto build_reply;
    }

    /* Bind session to display. */
    mtx_lock(&s->lock);
    s->active_display_id = req.display_id;
    if (s->active_display_handle == 0)
        s->active_display_handle = s->next_display_handle++;
    rep.display_handle = s->active_display_handle;
    rep.active_display_id = s->active_display_id;
    mtx_unlock(&s->lock);

build_reply:
    {
        /* Build reply frame with payload rep. */
        uint32_t payload_bytes;
        uint32_t msg_bytes;
        uint32_t msg_bytes_aligned;
        uint32_t frame_bytes;

        uint8_t *out;
        struct drawfs_frame_hdr fh;
        struct drawfs_msg_hdr mh;

        payload_bytes = (uint32_t)sizeof(rep);
        msg_bytes = (uint32_t)sizeof(struct drawfs_msg_hdr) + payload_bytes;
        msg_bytes_aligned = drawfs_align4(msg_bytes);
        frame_bytes = (uint32_t)sizeof(struct drawfs_frame_hdr) + msg_bytes_aligned;

        out = malloc(frame_bytes, M_DRAWFS, M_WAITOK | M_ZERO);

        fh.magic = DRAWFS_MAGIC;
        fh.version = DRAWFS_VERSION;
        fh.header_bytes = (uint16_t)sizeof(struct drawfs_frame_hdr);
        fh.frame_bytes = frame_bytes;
        fh.frame_id = s->next_out_frame_id++;

        mh.msg_type = DRAWFS_RPL_DISPLAY_OPEN;
        mh.msg_flags = 0;
        mh.msg_bytes = msg_bytes;
        mh.msg_id = msg_id;
        mh.reserved = 0;

        memcpy(out, &fh, sizeof(fh));
        memcpy(out + sizeof(fh), &mh, sizeof(mh));
        memcpy(out + sizeof(fh) + sizeof(mh), &rep, sizeof(rep));

        int err = drawfs_enqueue_event(s, out, frame_bytes);
        free(out, M_DRAWFS);
        return (err);
    }
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
    
case DRAWFSGIOC_MAP_SURFACE:
{
    struct drawfs_map_surface *ms;
    struct drawfs_surface *sf;

    ms = (struct drawfs_map_surface *)data;
    ms->status = 0;
    ms->stride_bytes = 0;
    ms->bytes_total = 0;

    if (ms->surface_id == 0) {
        ms->status = EINVAL;
        break;
    }

    sf = NULL;
    mtx_lock(&s->lock);
    TAILQ_FOREACH(sf, &s->surfaces, link) {
        if (sf->id == ms->surface_id)
            break;
    }
    if (sf != NULL) {
        s->map_surface_id = ms->surface_id;
        ms->stride_bytes = sf->stride_bytes;
        ms->bytes_total = sf->bytes_total;
    }
    mtx_unlock(&s->lock);

    if (sf == NULL)
        ms->status = ENOENT;

    break;
	return (0);

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

        mtx_unlock(&s->lock);
        return (0);
    }
    default:
        return (ENOTTY);
    }
	return (0);
}



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

    seldrain(&s->sel);
    cv_destroy(&s->cv);
    mtx_destroy(&s->lock);
    free(s, M_DRAWFS);
}

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

    if (s->closing) {
        s->stats.events_dropped += 1;
        mtx_unlock(&s->lock);
        free(ev->bytes, M_DRAWFS);
        free(ev, M_DRAWFS);
        return (ENXIO);
    }

    TAILQ_INSERT_TAIL(&s->evq, ev, link);
    s->evq_bytes += len;

    s->stats.events_enqueued += 1;
    s->stats.bytes_out += (uint64_t)len;

    cv_signal(&s->cv);
    selwakeup(&s->sel);

    mtx_unlock(&s->lock);

    return (0);
}

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

        v = drawfs_validate_frame(frame, frame_bytes, &fh, &err_off);
        if (v != DRAWFS_ERR_OK) {
            s->stats.frames_invalid += 1;
            (void)drawfs_reply_error(s, 0, (uint32_t)v, err_off);
            free(frame, M_DRAWFS);
            continue;
        }

        (void)drawfs_process_frame(s, frame, frame_bytes);
        s->stats.frames_processed += 1;
        free(frame, M_DRAWFS);
    }
}

static int
drawfs_validate_frame(const uint8_t *buf, size_t n, struct drawfs_frame_hdr *out_hdr, uint32_t *out_err_offset)
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

static int
drawfs_process_frame(struct drawfs_session *s, const uint8_t *buf, size_t n)
{
    struct drawfs_frame_hdr fh;
    uint32_t err_off;
    int v;

    v = drawfs_validate_frame(buf, n, &fh, &err_off);
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

        default:
            s->stats.messages_unsupported += 1;
            (void)drawfs_reply_error(s, mh.msg_id, DRAWFS_ERR_UNSUPPORTED_CAP, pos);
            break;
        }

        pos = drawfs_align4(msg_end);
    }

    return (0);
}

static int
drawfs_reply_ok(struct drawfs_session *s, uint32_t msg_id)
{
    uint8_t out[sizeof(struct drawfs_frame_hdr) + sizeof(struct drawfs_msg_hdr)];
    struct drawfs_frame_hdr fh;
    struct drawfs_msg_hdr mh;

    fh.magic = DRAWFS_MAGIC;
    fh.version = DRAWFS_VERSION;
    fh.header_bytes = (uint16_t)sizeof(struct drawfs_frame_hdr);
    fh.frame_bytes = (uint32_t)sizeof(out);
    fh.frame_id = s->next_out_frame_id++;

    mh.msg_type = DRAWFS_RPL_OK;
    mh.msg_flags = 0;
    mh.msg_bytes = (uint32_t)sizeof(struct drawfs_msg_hdr);
    mh.msg_id = msg_id;
    mh.reserved = 0;

    memcpy(out, &fh, sizeof(fh));
    memcpy(out + sizeof(fh), &mh, sizeof(mh));

    return drawfs_enqueue_event(s, out, sizeof(out));
}

static int
drawfs_reply_error(struct drawfs_session *s, uint32_t msg_id, uint32_t err_code, uint32_t err_offset)
{
    uint8_t out[sizeof(struct drawfs_frame_hdr) + sizeof(struct drawfs_msg_hdr) + sizeof(struct drawfs_rpl_error)];
    struct drawfs_frame_hdr fh;
    struct drawfs_msg_hdr mh;
    struct drawfs_rpl_error ep;

    fh.magic = DRAWFS_MAGIC;
    fh.version = DRAWFS_VERSION;
    fh.header_bytes = (uint16_t)sizeof(struct drawfs_frame_hdr);
    fh.frame_bytes = (uint32_t)sizeof(out);
    fh.frame_id = s->next_out_frame_id++;

    mh.msg_type = DRAWFS_RPL_ERROR;
    mh.msg_flags = 0;
    mh.msg_bytes = (uint32_t)(sizeof(struct drawfs_msg_hdr) + sizeof(struct drawfs_rpl_error));
    mh.msg_id = msg_id;
    mh.reserved = 0;

    ep.err_code = err_code;
    ep.err_detail = 0;
    ep.err_offset = err_offset;

    memcpy(out, &fh, sizeof(fh));
    memcpy(out + sizeof(fh), &mh, sizeof(mh));
    memcpy(out + sizeof(fh) + sizeof(mh), &ep, sizeof(ep));

    return drawfs_enqueue_event(s, out, sizeof(out));
}

static int
drawfs_reply_hello(struct drawfs_session *s, uint32_t msg_id)
{
    uint8_t out[sizeof(struct drawfs_frame_hdr) + sizeof(struct drawfs_msg_hdr) + sizeof(struct drawfs_rpl_hello)];
    struct drawfs_frame_hdr fh;
    struct drawfs_msg_hdr mh;
    struct drawfs_rpl_hello hp;

    fh.magic = DRAWFS_MAGIC;
    fh.version = DRAWFS_VERSION;
    fh.header_bytes = (uint16_t)sizeof(struct drawfs_frame_hdr);
    fh.frame_bytes = (uint32_t)sizeof(out);
    fh.frame_id = s->next_out_frame_id++;

    mh.msg_type = DRAWFS_RPL_HELLO;
    mh.msg_flags = 0;
    mh.msg_bytes = (uint32_t)(sizeof(struct drawfs_msg_hdr) + sizeof(struct drawfs_rpl_hello));
    mh.msg_id = msg_id;
    mh.reserved = 0;

    hp.server_major = 1;
    hp.server_minor = 0;
    hp.server_flags = 0;
    hp.caps_bytes = 0;

    memcpy(out, &fh, sizeof(fh));
    memcpy(out + sizeof(fh), &mh, sizeof(mh));
    memcpy(out + sizeof(fh) + sizeof(mh), &hp, sizeof(hp));

    return drawfs_enqueue_event(s, out, sizeof(out));
}

static int
drawfs_reply_display_list(struct drawfs_session *s, uint32_t msg_id)
{
    /*
     * Step 8: Return a real DISPLAY_LIST payload.
     *
     * For now we report a single stub display:
     *   id=1, 1920x1080 @ 60 Hz.
     *
     * This will later be backed by DRM/KMS enumeration.
     */
    const uint32_t count = 1;
    struct drawfs_display_desc desc;

    desc.display_id = 1;
    desc.width_px = 1920;
    desc.height_px = 1080;
    desc.refresh_mhz = 60000;
    desc.flags = 0;

    /* Build payload: count + desc[count]. */
    const uint32_t payload_bytes = (uint32_t)(sizeof(count) + sizeof(desc));

    /* Message bytes include header, payload is 4-byte aligned. */
    const uint32_t msg_bytes = (uint32_t)sizeof(struct drawfs_msg_hdr) + payload_bytes;
    const uint32_t msg_bytes_aligned = drawfs_align4(msg_bytes);

    /* Frame bytes include frame header + aligned message. */
    const uint32_t frame_bytes = (uint32_t)sizeof(struct drawfs_frame_hdr) + msg_bytes_aligned;

    uint8_t *out = malloc(frame_bytes, M_DRAWFS, M_WAITOK | M_ZERO);
    struct drawfs_frame_hdr fh;
    struct drawfs_msg_hdr mh;

    fh.magic = DRAWFS_MAGIC;
    fh.version = DRAWFS_VERSION;
    fh.header_bytes = (uint16_t)sizeof(struct drawfs_frame_hdr);
    fh.frame_bytes = frame_bytes;
    fh.frame_id = s->next_out_frame_id++;

    mh.msg_type = DRAWFS_RPL_DISPLAY_LIST;
    mh.msg_flags = 0;
    mh.msg_bytes = msg_bytes;
    mh.msg_id = msg_id;
    mh.reserved = 0;

    memcpy(out, &fh, sizeof(fh));
    memcpy(out + sizeof(fh), &mh, sizeof(mh));

    /* Payload immediately after msg header */
    uint8_t *p = out + sizeof(fh) + sizeof(mh);
    memcpy(p, &count, sizeof(count));
    memcpy(p + sizeof(count), &desc, sizeof(desc));

    /* Remaining padding is already zero due to M_ZERO. */

    int err = drawfs_enqueue_event(s, out, frame_bytes);
    free(out, M_DRAWFS);
    return (err);
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
        drawfs_dev = make_dev(&drawfs_cdevsw, 0, UID_ROOT, GID_WHEEL, 0600, DRAWFS_DEVNAME);
        uprintf("drawfs loaded, device %s created\n", DRAWFS_NODEPATH);
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
