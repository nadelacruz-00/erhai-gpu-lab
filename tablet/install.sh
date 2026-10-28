#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
#
# Install or remove the erhai GPU lab tool.
#
#   sudo tablet/install.sh            install
#   sudo tablet/install.sh uninstall  remove the tool, keep evidence
#
# Installs only /usr/local/sbin/erhai-gpu-lab (from tablet/erhai-lab) and
# /var/lib/erhai-gpu. It changes no GPU or runtime-PM setting: rungs set and
# restore their own.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SBIN=/usr/local/sbin/erhai-gpu-lab
STATE=/var/lib/erhai-gpu

[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

case "${1:-install}" in
install)
	install -m 0755 "$HERE/erhai-lab" "$SBIN"
	install -d -m 0755 "$STATE"
	echo "installed $SBIN"
	;;
uninstall)
	rm -f "$SBIN"
	echo "removed $SBIN (evidence kept in $STATE)"
	;;
*)
	echo "usage: $0 [install|uninstall]" >&2
	exit 2
	;;
esac
