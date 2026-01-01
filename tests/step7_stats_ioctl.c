#include <sys/types.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <err.h>

#include "drawfs_ioctl.h"

static void
print_stats(const char *tag, const struct drawfs_stats *st)
{
    printf("== %s ==\n", tag);
    printf("frames_received      %llu\n", (unsigned long long)st->frames_received);
    printf("frames_processed     %llu\n", (unsigned long long)st->frames_processed);
    printf("frames_invalid       %llu\n", (unsigned long long)st->frames_invalid);
    printf("messages_processed   %llu\n", (unsigned long long)st->messages_processed);
    printf("messages_unsupported %llu\n", (unsigned long long)st->messages_unsupported);
    printf("events_enqueued      %llu\n", (unsigned long long)st->events_enqueued);
    printf("events_dropped       %llu\n", (unsigned long long)st->events_dropped);
    printf("bytes_in             %llu\n", (unsigned long long)st->bytes_in);
    printf("bytes_out            %llu\n", (unsigned long long)st->bytes_out);
    printf("evq_depth            %u\n", st->evq_depth);
    printf("inbuf_bytes          %u\n", st->inbuf_bytes);
}

int
main(void)
{
    int fd = open("/dev/draw", O_RDWR);
    if (fd < 0)
        err(1, "open(/dev/draw)");

    struct drawfs_stats st;
    memset(&st, 0, sizeof(st));

    if (ioctl(fd, DRAWFSGIOC_STATS, &st) != 0)
        err(1, "ioctl(DRAWFSGIOC_STATS)");

    print_stats("current", &st);
    close(fd);
    return 0;
}
