#!/bin/bash
# One-time setup so the web station can change the Jetson power mode, max clocks and fan.
#   sudo ./scripts/jetson/install-power-control.sh            allow the user who ran sudo
#   sudo ./scripts/jetson/install-power-control.sh --remove   undo
# It installs a small root helper (accepting only fixed commands) and a sudoers rule that lets
# that one user run only that helper without a password.
set -euo pipefail
HELPER=/usr/local/sbin/aoi-jetson-power
RULE=/etc/sudoers.d/rmutt-aoi-power
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

[[ $EUID -eq 0 ]] || { echo "Run with sudo: sudo $0" >&2; exit 1; }
[[ -f /etc/nv_tegra_release ]] || { echo "This is not an NVIDIA Jetson; nothing to do." >&2; exit 1; }

if [[ "${1:-}" == "--remove" ]]; then
    rm -f "$RULE" "$HELPER"
    echo "Removed $HELPER and $RULE"
    exit 0
fi

USER_NAME="${SUDO_USER:-}"
[[ -n "$USER_NAME" && "$USER_NAME" != root ]] || { echo "Run it with sudo from the station user's account (not as root)." >&2; exit 1; }
[[ "$USER_NAME" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "Unexpected user name: $USER_NAME" >&2; exit 1; }

install -o root -g root -m 755 "$HERE/aoi-jetson-power" "$HELPER"
TMP="$(mktemp)"
echo "$USER_NAME ALL=(root) NOPASSWD: $HELPER" > "$TMP"
visudo -cf "$TMP" >/dev/null || { rm -f "$TMP"; echo "sudoers rule failed validation; nothing changed." >&2; exit 1; }
install -o root -g root -m 440 "$TMP" "$RULE"
rm -f "$TMP"
sudo -u "$USER_NAME" sudo -n "$HELPER" check && echo "✓ Power control enabled for $USER_NAME (helper: $HELPER)"
