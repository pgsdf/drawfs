#!/bin/sh
set -eu

# drawfs build and install helper for FreeBSD src tree
# Copies sys/dev/drawfs and sys/modules/drawfs into /usr/src, builds the kmod,
# and (optionally) loads it.

SRCROOT=${SRCROOT:-/usr/src}
OBJDIR=""

echo "== drawfs: install sources into ${SRCROOT} =="
sudo rsync -a sys/dev/drawfs/ "${SRCROOT}/sys/dev/drawfs/"
sudo rsync -a sys/modules/drawfs/ "${SRCROOT}/sys/modules/drawfs/"

echo "== drawfs: build kmod =="
cd "${SRCROOT}/sys/modules/drawfs"
sudo make clean
sudo make

OBJDIR=$(sudo make -V .OBJDIR)
echo "OBJDIR=${OBJDIR}"

if [ "${1:-}" = "load" ]; then
  echo "== drawfs: load module =="
  sudo kldunload drawfs 2>/dev/null || true
  sudo kldload "${OBJDIR}/drawfs.ko"
  echo "Loaded: ${OBJDIR}/drawfs.ko"
fi

echo "Done."
