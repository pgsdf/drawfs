#!/bin/sh
#
# drawfs build helper
#
# Goals:
#   - Make repo -> /usr/src installation reproducible
#   - Avoid "stale /usr/src tree" issues during iteration
#
set -eu

REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SRCROOT=${SRCROOT:-/usr/src}

DEVDEST="$SRCROOT/sys/dev/drawfs"
MODDEST="$SRCROOT/sys/modules/drawfs"
KMODDIR="$MODDEST"

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "This script must run as root."
    echo "Try: sudo $0 $*"
    exit 1
  fi
}

usage() {
  cat <<'USAGE'
Usage:
  sudo ./build.sh install
  sudo ./build.sh build
  sudo ./build.sh load
  sudo ./build.sh unload
  sudo ./build.sh test [tests/stepXX_*.py]
  sudo ./build.sh all [tests/stepXX_*.py]
  ./build.sh verify
  ./build.sh help

Environment:
  SRCROOT=/usr/src   Root of FreeBSD source tree (default: /usr/src)

Notes:
  - install uses rsync --delete, so /usr/src/sys/dev/drawfs and /usr/src/sys/modules/drawfs
    will be overwritten to match this repo.
  - build uses the in-tree kernel module build system under /usr/src/sys/modules/drawfs
USAGE
}

cmd=${1:-help}
shift || true

case "$cmd" in
  help|-h|--help)
    usage
    ;;

  install)
    need_root "$cmd"
    echo "Installing drawfs sources into $SRCROOT"
    mkdir -p "$DEVDEST" "$MODDEST"
    rsync -a --delete "$REPO_ROOT/sys/dev/drawfs/" "$DEVDEST/"
    rsync -a --delete "$REPO_ROOT/sys/modules/drawfs/" "$MODDEST/"
    echo "OK: install"
    ;;

  build)
    need_root "$cmd"
    echo "Building kernel module in $KMODDIR"
    ( cd "$KMODDIR" && make clean && make )
    echo "OK: build"
    ;;

  load)
    need_root "$cmd"
    OBJDIR=$(make -C "$KMODDIR" -V .OBJDIR)
    KO="$OBJDIR/drawfs.ko"
    if [ ! -f "$KO" ]; then
      echo "ERROR: missing $KO"
      echo "Run: sudo ./build.sh build"
      exit 1
    fi
    echo "Loading $KO"
    kldunload drawfs 2>/dev/null || true
    kldload "$KO"
    echo "OK: load"
    ;;

  unload)
    need_root "$cmd"
    kldunload drawfs 2>/dev/null || true
    echo "OK: unload"
    ;;

  test)
    need_root "$cmd"
    testfile=${1:-tests/step11_surface_mmap_test.py}
    if [ ! -f "$REPO_ROOT/$testfile" ]; then
      echo "ERROR: test file not found: $testfile"
      exit 1
    fi
    echo "Running $testfile"
    ( cd "$REPO_ROOT" && python3 "$testfile" )
    echo "OK: test"
    ;;

  all)
    need_root "$cmd"
    testfile=${1:-tests/step11_surface_mmap_test.py}
    "$0" install
    "$0" build
    "$0" load
    "$0" test "$testfile"
    ;;

  verify)
    echo "Repo root: $REPO_ROOT"
    echo "SRCROOT:   $SRCROOT"
    echo
    echo "Repo dev drawfs.c:"
    ls -l "$REPO_ROOT/sys/dev/drawfs/drawfs.c" 2>/dev/null || true
    echo "Installed dev drawfs.c:"
    ls -l "$DEVDEST/drawfs.c" 2>/dev/null || true
    echo
    echo "Installed symbol check (surface_present):"
    if [ -f "$DEVDEST/drawfs.c" ]; then
      grep -n "drawfs_reply_surface_present" "$DEVDEST/drawfs.c" || true
    fi
    echo
    echo "Module OBJDIR:"
    make -C "$KMODDIR" -V .OBJDIR 2>/dev/null || true
    ;;

  *)
    echo "Unknown command: $cmd"
    echo
    usage
    exit 2
    ;;
esac
