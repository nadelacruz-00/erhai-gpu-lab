#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
#
# Fail unless every symbol a candidate's extra.config requests made it into the
# final .config unchanged.  merge_config.sh + olddefconfig drop a symbol
# silently when one of its dependencies is unmet (DPM_WATCHDOG needs PM_DEBUG,
# PSTORE and EXPERT), and the build still succeeds.
#
#   ci/assert-config.sh <extra.config> <.config>
set -euo pipefail

FRAG=${1:?usage: assert-config.sh <extra.config> <.config>}
CONFIG=${2:?usage: assert-config.sh <extra.config> <.config>}

fail=0
while IFS= read -r line || [ -n "$line" ]; do
	case "$line" in
	CONFIG_*=*)
		sym=${line%%=*}
		;;
	"# CONFIG_"*" is not set")
		sym=${line#"# "}
		sym=${sym%" is not set"}
		;;
	*)
		continue
		;;
	esac
	if ! grep -qxF -- "$line" "$CONFIG"; then
		got=$(grep -E "^(# )?$sym[= ]" "$CONFIG" || echo "(absent)")
		echo "config assert: wanted '$line', got '$got'" >&2
		fail=1
	fi
done < "$FRAG"

if [ "$fail" -ne 0 ]; then
	echo "config assert: FAILED for $FRAG" >&2
	exit 1
fi
echo "config assert: every symbol in $FRAG is present"
