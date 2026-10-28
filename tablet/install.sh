#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
#
# Install or remove the erhai-lab charging kit.
#
#   sudo tablet/install.sh            install
#   sudo tablet/install.sh uninstall  remove the tool, keep evidence
#
# Installs only /usr/local/sbin/erhai-lab and /var/lib/erhai-charging. It
# changes no charging parameter: experiments set and restore their own.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SBIN=/usr/local/sbin/erhai-lab

[ "$(id -u)" = 0 ] || { echo "run with sudo" >&2; exit 1; }

case "${1:-install}" in
install)
	install -m 0755 "$HERE/erhai-lab" "$SBIN"
	install -d -m 0755 /var/lib/erhai-charging
	echo "installed $SBIN"
	;;
uninstall)
	rm -f "$SBIN"
	echo "removed $SBIN (evidence kept in /var/lib/erhai-charging)"
	;;
*)
	echo "usage: $0 [install|uninstall]" >&2
	exit 2
	;;
esac
