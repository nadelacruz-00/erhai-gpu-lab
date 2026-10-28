#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
#
# Install or remove the erhai GPU lab tool.
#
#   sudo tablet/install.sh            install
#   sudo tablet/install.sh uninstall  remove the tool, keep evidence
#
# Installs /usr/local/sbin/erhai-gpu-lab (from tablet/erhai-lab), its helpers
# under /usr/local/lib/erhai-gpu-lab (gpu-checks.sh, setup.sh, igt-recovery),
# the systemd units (erhai-gpu-lab-boot.service, erhai-gpu-lab-soak.*) and
# /var/lib/erhai-gpu. Only the boot service is enabled; the soak timer stays
# disabled until the operator enables it. It changes no GPU or runtime-PM
# setting: rungs set and restore their own.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")
SBIN=/usr/local/sbin/erhai-gpu-lab
LIB=/usr/local/lib/erhai-gpu-lab
UNITS=/etc/systemd/system
STATE=/var/lib/erhai-gpu
UNIT_FILES="erhai-gpu-lab-boot.service erhai-gpu-lab-soak.service erhai-gpu-lab-soak.timer"

[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

case "${1:-install}" in
install)
	install -m 0755 "$HERE/erhai-lab" "$SBIN"
	install -d -m 0755 "$LIB"
	install -m 0755 "$HERE/gpu-checks.sh" "$LIB/gpu-checks.sh"
	install -m 0755 "$HERE/setup.sh" "$LIB/setup.sh"
	install -m 0755 "$ROOT/tools/igt-recovery/igt-recovery" "$LIB/igt-recovery"
	install -d -m 0755 "$STATE"
	for u in $UNIT_FILES; do
		[ -f "$HERE/$u" ] && install -m 0644 "$HERE/$u" "$UNITS/$u"
	done
	systemctl daemon-reload
	[ -f "$HERE/erhai-gpu-lab-boot.service" ] && systemctl enable erhai-gpu-lab-boot.service
	echo "installed $SBIN and helpers in $LIB"
	;;
uninstall)
	systemctl disable --now erhai-gpu-lab-boot.service 2>/dev/null || true
	systemctl disable --now erhai-gpu-lab-soak.timer 2>/dev/null || true
	for u in $UNIT_FILES; do
		rm -f "$UNITS/$u"
	done
	systemctl daemon-reload
	rm -f "$SBIN"
	rm -rf "$LIB"
	echo "removed $SBIN, $LIB and the units (evidence kept in $STATE)"
	;;
*)
	echo "usage: $0 [install|uninstall]" >&2
	exit 2
	;;
esac
