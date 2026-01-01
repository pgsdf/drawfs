CC?=cc
CFLAGS?=-O2 -Wall -Wextra

all: step7_stats_ioctl

step7_stats_ioctl: step7_stats_ioctl.c
	$(CC) $(CFLAGS) -I. -o $@ step7_stats_ioctl.c

clean:
	rm -f step7_stats_ioctl
