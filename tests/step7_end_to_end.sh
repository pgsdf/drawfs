#!/bin/sh
set -eu

echo "Building ioctl test..."
( cd "$(dirname "$0")" && make )

echo "Stats (fresh session):"
sudo ./step7_stats_ioctl

echo "Step 7B: stats on same fd:"
sudo python3 ./step7B_stats_same_fd.py
