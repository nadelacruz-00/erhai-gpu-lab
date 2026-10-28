#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Install the ladder tools on the tablet. Idempotent: a second run only
# prints "<pkg> already installed". Exits 1 (without prompting) if packages
# are missing and neither root nor passwordless sudo is available.
set -u

PKGS=(trace-cmd mesa-utils vulkan-tools libegl-dev libgles-dev)
missing=()
for p in "${PKGS[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 && echo "$p already installed" || missing+=("$p")
done
[ ${#missing[@]} -eq 0 ] && exit 0

if [ "$(id -u)" -eq 0 ]; then
    SUDO=()
elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    SUDO=(sudo)
else
    echo "setup.sh: missing: ${missing[*]}; need root or passwordless sudo to install" >&2
    echo "setup.sh: run: sudo apt-get install -y ${missing[*]}" >&2
    exit 1
fi
"${SUDO[@]}" apt-get install -y "${missing[@]}"
