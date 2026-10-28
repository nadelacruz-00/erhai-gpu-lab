#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Build a candidate on this machine exactly as CI does (ci/build-candidate.sh),
# from a local kernel checkout instead of GitHub, with a live progress line.
# The assets land in out/<candidate>/; install them with
#   sudo erhai-gpu-lab fetch <candidate> --from-dir out/<candidate>
set -euo pipefail

usage() { echo "usage: $0 <candidate> [--kernel-dir DIR] [--interval SECS]" >&2; exit 2; }

[ $# -ge 1 ] || usage
CAND=$1
shift
KDIR=$HOME/Development/oneplus-erhai-linux
INTERVAL=2
while [ $# -gt 0 ]; do
    case $1 in
        --kernel-dir) [ $# -ge 2 ] || usage; KDIR=$2; shift 2 ;;
        --interval) [ $# -ge 2 ] || usage; INTERVAL=$2; shift 2 ;;
        *) usage ;;
    esac
done
case $INTERVAL in ''|*[!0-9.]*) usage ;; esac

LAB=$(cd "$(dirname "$0")/.." && pwd)
[ -d "$LAB/candidates/$CAND" ] || { echo "build-local: no candidate dir candidates/$CAND" >&2; exit 2; }
git -C "$KDIR" cat-file -e "$(tr -d '[:space:]' < "$LAB/candidates/BASE_SHA")^{commit}" 2>/dev/null ||
    { echo "build-local: $KDIR does not have BASE_SHA; fetch it there first" >&2; exit 2; }
BUILD=${BUILD_CMD:-$LAB/ci/build-candidate.sh}   # test seam

STATE=$LAB/out/.build-local
mkdir -p "$STATE"
LOG=$STATE/$CAND.log
COUNT_FILE=$STATE/$CAND.objects        # object count of the last full build
TIMES=$STATE/times.log

# Compile with CI's gcc major (ubuntu-24.04-arm ships gcc 13): the tablet's
# gcc 15 builds a different image (RELR relocations, 8 MB smaller) that has
# not been shown to boot. CI_GCC= (empty) builds with the default gcc.
CI_GCC=${CI_GCC-13}
if [ -n "$CI_GCC" ]; then
    if command -v "gcc-$CI_GCC" >/dev/null; then
        TC=$STATE/toolchain-gcc$CI_GCC
        mkdir -p "$TC"
        ln -sf "$(command -v "gcc-$CI_GCC")" "$TC/gcc"
        for t in ld ar nm objcopy objdump strip readelf as; do
            ln -sf "$(command -v "$t")" "$TC/$t"
        done
        export CROSS_COMPILE=$TC/
    else
        echo "build-local: gcc-$CI_GCC not installed (CI builds with it): sudo apt-get install -y gcc-$CI_GCC" >&2
        echo "build-local: or build with the default gcc ($(gcc -dumpversion)): CI_GCC= $0 $CAND" >&2
        exit 2
    fi
fi

# CPU clocks below the hardware max make the timing incomparable; say so.
for p in /sys/devices/system/cpu/cpufreq/policy*; do
    [ -r "$p/scaling_max_freq" ] || continue
    if [ "$(<"$p/scaling_max_freq")" -lt "$(<"$p/cpuinfo_max_freq")" ]; then
        echo "build-local: $(basename "$p") capped at $(( $(<"$p/scaling_max_freq") / 1000 )) MHz of $(( $(<"$p/cpuinfo_max_freq") / 1000 )) MHz; to lift until reboot:" >&2
        echo "  for p in /sys/devices/system/cpu/cpufreq/policy*; do sudo tee \$p/scaling_max_freq < \$p/cpuinfo_max_freq >/dev/null; done" >&2
        break
    fi
done

hottest() {   # hottest CPU sensor in C, or "?"
    local m=0 z t
    for z in /sys/class/thermal/thermal_zone*; do
        case $(<"$z/type") in cpu*|cpuss*) t=$(<"$z/temp"); [ "$t" -gt "$m" ] && m=$t ;; esac
    done 2>/dev/null
    [ "$m" -gt 0 ] && echo $((m / 1000)) || echo "?"
}
mhz() { [ -r "$1" ] && echo $(( $(<"$1") / 1000 )) || echo "?"; }
clamp() { [ -r "$1" ] && cat "$1" || echo "?"; }

phase() {   # coarse phase from the log
    if grep -q '^kernelrelease:' "$LOG" 2>/dev/null; then echo "package"
    elif grep -qE '^  (LD|CC) \[M\]' "$LOG" 2>/dev/null; then echo "modules"
    elif grep -qE '^  (CC|AS|LD) ' "$LOG" 2>/dev/null; then echo "compile"
    elif grep -q '^fetching ' "$LOG" 2>/dev/null; then echo "fetch/patch"
    else echo "start"; fi
}

fmt() { printf '%dm%02ds' $(($1 / 60)) $(($1 % 60)); }

TOTAL=$( [ -r "$COUNT_FILE" ] && cat "$COUNT_FILE" || echo 0 )
PEAK=0
T0=$(date +%s)
: > "$LOG"
# Own process group, so Ctrl-C stops make and every compiler it started.
KERNEL_REPO=$KDIR setsid "$BUILD" "$CAND" local >"$LOG" 2>&1 &
PID=$!
trap 'kill -TERM -- -$PID 2>/dev/null; echo; echo "build-local: interrupted (log: $LOG)"; exit 130' INT TERM

TTY=0; [ -t 1 ] && TTY=1
LAST_PLAIN=0
while kill -0 "$PID" 2>/dev/null; do
    now=$(date +%s); el=$((now - T0))
    objs=$(grep -cE '^  (CC|AS)( \[M\])? ' "$LOG" 2>/dev/null || true)
    t=$(hottest); [ "$t" != "?" ] && [ "$t" -gt "$PEAK" ] && PEAK=$t
    prog="$objs obj"
    if [ "$TOTAL" -gt 0 ] && [ "$objs" -gt 0 ]; then
        pct=$((objs * 100 / TOTAL)); [ $pct -gt 99 ] && pct=99
        eta=$(( el * (TOTAL - objs) / objs )); [ $eta -lt 0 ] && eta=0
        prog="$objs/$TOTAL obj ${pct}% eta $(fmt $eta)"
    fi
    line="[$(fmt $el)] $(phase) | $prog | ${t}C peak ${PEAK}C | $(mhz /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq)/$(mhz /sys/devices/system/cpu/cpufreq/policy6/scaling_cur_freq) MHz | clamp $(clamp /sys/class/thermal/cooling_device0/cur_state)/$(clamp /sys/class/thermal/cooling_device1/cur_state)"
    if [ $TTY = 1 ]; then
        cols=$(tput cols 2>/dev/null || echo 120)
        last=$(tail -n1 "$LOG" 2>/dev/null | tr -d '\r' | sed 's/^ *//')
        printf '\r\033[K%s\n\033[K  %s\033[1A' "${line:0:$cols}" "${last:0:$((cols - 2))}"
    elif [ $((now - LAST_PLAIN)) -ge 30 ]; then
        echo "$line"; LAST_PLAIN=$now
    fi
    sleep "$INTERVAL"
done
set +e
wait "$PID"; rc=$?
set -e
EL=$(( $(date +%s) - T0 ))
[ $TTY = 1 ] && printf '\r\033[K\n\033[K\033[1A'
objs=$(grep -cE '^  (CC|AS)( \[M\])? ' "$LOG" 2>/dev/null || true)
echo "$(date -Is) cand=$CAND rc=$rc elapsed=${EL}s objects=$objs peakC=$PEAK" >> "$TIMES"
if [ "$rc" -ne 0 ]; then
    echo "build-local: FAILED rc=$rc after $(fmt $EL); last lines of $LOG:"
    tail -n 15 "$LOG"
    exit "$rc"
fi
# Keep the count of a full build only; an incremental rebuild compiles fewer.
if [ "$objs" -gt 0 ] && [ "$objs" -ge $((TOTAL * 9 / 10)) ]; then echo "$objs" > "$COUNT_FILE"; fi
echo "build-local: $CAND built in $(fmt $EL) ($objs objects, peak ${PEAK}C); assets in out/$CAND/"
echo "install: sudo erhai-gpu-lab fetch $CAND --from-dir $LAB/out/$CAND"
