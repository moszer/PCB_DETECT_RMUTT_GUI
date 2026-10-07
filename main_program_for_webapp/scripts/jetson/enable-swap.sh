#!/usr/bin/env bash
# Add a swap file on the Jetson so a memory spike (YOLO + CUDA + the browser) slows things down
# instead of the kernel killing the station. Idempotent: run again to check or resize.
#
#   sudo scripts/jetson/enable-swap.sh          # 8 GB at /swapfile
#   sudo scripts/jetson/enable-swap.sh 4G       # another size
set -euo pipefail
SIZE="${1:-8G}"
FILE=/swapfile
[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo $0 ${1:-}"; exit 1; }

if swapon --show=NAME --noheadings | grep -qx "$FILE"; then
  echo "✓ $FILE is already in use:"; swapon --show
else
  if [[ ! -f $FILE ]]; then
    echo "→ Creating $SIZE swap file at $FILE"
    fallocate -l "$SIZE" "$FILE" || dd if=/dev/zero of="$FILE" bs=1M count=$(( $(numfmt --from=iec "$SIZE") / 1048576 )) status=progress
  fi
  chmod 600 "$FILE"
  mkswap "$FILE" >/dev/null
  swapon "$FILE"
  echo "✓ Swap on:"; swapon --show
fi
grep -q "^$FILE " /etc/fstab || { echo "$FILE none swap sw 0 0" >> /etc/fstab; echo "✓ Added to /etc/fstab (kept after reboot)"; }
# Use swap only under pressure: keep the model and frames in RAM as long as possible.
echo "vm.swappiness=10" > /etc/sysctl.d/90-aoi-swap.conf
sysctl -q -p /etc/sysctl.d/90-aoi-swap.conf
echo "✓ vm.swappiness=10"
free -h
