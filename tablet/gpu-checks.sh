#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# GPU ladder checks for the OnePlus Pad 3 (erhai).
#   gpu-checks.sh g0              boot checks: one "PASS|FAIL|INFO <id> <value>" line each;
#                                 exit 1 if any FAIL
#   gpu-checks.sh cycles [secs]   count GPU runtime-PM cycles with trace-cmd
#
# Test/override env: SYSROOT (/), DMESG_CMD, MAPS_PID, PIN_STATE, PIN_CONF,
# PIN_WAIT (poll limit s; default SETTLE+TIMEOUT), SUSPEND_WAIT (default 60),
# PON_REASON_PATH (default empty), EGLINFO_FILE, GENPD_SUMMARY_FILE, TRACE_REPORT.
set -u

SYSROOT=${SYSROOT:-/}
SYSROOT=${SYSROOT%/}
DMESG_CMD=${DMESG_CMD:-journalctl -k -b -q --no-pager}
PIN_STATE=${PIN_STATE:-/run/erhai-gpu-pin-once.state}
PIN_CONF=${PIN_CONF:-/etc/erhai/gpu-pin.conf}
SUSPEND_WAIT=${SUSPEND_WAIT:-60}
PON_REASON_PATH=${PON_REASON_PATH:-}
GPU_DEV=3d00000.gpu
GPU_DEV_RE='3d00000\.gpu'
# Devices whose PM callbacks are this work's: the GPU, any GMU, gxclkctl.
GPU_PM_DEV_RE='3d00000\.gpu|[0-9a-f]+\.gmu|3d64000\.clock-controller|gxclkctl'
# A WARNING/Call-trace block naming one of these is GPU-attributed.
GPU_STACK_RE='a6xx_|a8xx_|adreno|msm_gpu|gdsc|gxclkctl|gmu'
GPU_DIR=$SYSROOT/sys/devices/platform/soc@0/$GPU_DEV

failed=0
report() { # status id value
    printf '%s %s %s\n' "$1" "$2" "$3"
    if [ "$1" = FAIL ]; then failed=1; fi
    return 0
}
verdict() { # id ok-value fail-value command...
    local id=$1 okv=$2 failv=$3
    shift 3
    if "$@"; then report PASS "$id" "$okv"; else report FAIL "$id" "$failv"; fi
}

DMESG=
DMESG_OK=1
load_dmesg() {
    local rc=0
    DMESG=$(bash -c "$DMESG_CMD" 2>/dev/null) || rc=$?
    if [ "$rc" -ne 0 ]; then
        DMESG_OK=0; report FAIL dmesg-readable "dmesg unavailable (DMESG_CMD exit $rc)"
    elif [ -z "$DMESG" ]; then
        DMESG_OK=0; report FAIL dmesg-readable "dmesg unavailable (empty output)"
    fi
}
dm_has() { grep -Eq -- "$1" <<<"$DMESG"; }
dm_lacks() { ! dm_has "$1"; }
dmesg_needed() { [ "$DMESG_OK" = 1 ] && return 1; report FAIL "$1" "dmesg unavailable"; return 0; }
link_target() { local t; t=$(readlink "$1" 2>/dev/null) && basename "$t"; }

check_gxclkctl_bound() {
    local d; d=$(link_target "$SYSROOT/sys/devices/platform/soc@0/3d64000.clock-controller/driver")
    verdict gxclkctl-bound "$d" "driver=${d:-none}" [ "$d" = gxclkctl-kaanapali ]
}
check_gmu_genpd() {
    local p dev seen=
    while IFS= read -r p; do
        dev=${p##*/genpd:0:}
        seen="$seen${seen:+,}$dev"
        if [ -n "$(find "$SYSROOT/sys/devices" -name "genpd:1:$dev" 2>/dev/null | head -1)" ]; then
            report PASS gmu-genpd "$dev genpd:0,genpd:1"; return
        fi
    done < <(find "$SYSROOT/sys/devices" -name 'genpd:0:*.gmu' 2>/dev/null | sort)
    if [ -n "$seen" ]; then
        report FAIL gmu-genpd "genpd:1 missing for ${seen}"
    else
        report FAIL gmu-genpd "no genpd:0:*.gmu"
    fi
}
check_gx_gdsc() {
    local s
    if [ -n "${GENPD_SUMMARY_FILE:-}" ]; then
        s=$(cat "$GENPD_SUMMARY_FILE" 2>/dev/null)
    else
        s=$(sudo -n cat "$SYSROOT/sys/kernel/debug/pm_genpd/pm_genpd_summary" 2>/dev/null)
    fi
    if [ -z "$s" ]; then report FAIL gx-gdsc-summary "unreadable (no sudo / debugfs unreadable)"; return; fi
    verdict gx-gdsc-summary gx_clkctl_gx_gdsc "gx_clkctl_gx_gdsc not in pm_genpd_summary" \
        grep -q gx_clkctl_gx_gdsc <<<"$s"
}
# Scan dmesg for oopses and WARNING/Call-trace blocks. Prints "FATAL <line>"
# (Oops/BUG), "GPU <header>" (a block whose header or stack names the GPU) and
# "UNRELATED <count>". A block runs from "[ cut here ]", "WARNING:" or "Call
# trace:" to "---[ end trace" or, after its stack, the first non-indented line.
# "Modules linked in:" and register dumps are not searched.
scan_traces() {
    awk -v gre="$GPU_STACK_RE" '
    function close_block() {
        if (!inb) return
        if (buf ~ gre) { if (gpu == "") gpu = hdr } else n++
        inb = 0; stk = 0; warned = 0; buf = ""; hdr = ""
    }
    {
        m = $0
        sub(/^\[ *[0-9.]+\] /, "", m)
        sub(/^[A-Z][a-z][a-z] +[0-9]+ [0-9:]+ [^ ]+ kernel: /, "", m)
        sub(/^[0-9T:.+-]+ [^ ]+ kernel: /, "", m)
    }
    m ~ /Oops|Unable to handle kernel|Internal error|BUG:/ { if (fatal == "") fatal = m }
    inb && stk && m !~ /^ / && m !~ /end trace/ { close_block() }
    m ~ /\[ cut here \]/ { close_block(); inb = 1; next }
    m ~ /^WARNING:/ && warned { close_block() }
    m ~ /^WARNING:|Call [Tt]race:/ && !inb { inb = 1 }
    inb {
        if (m ~ /^WARNING:/) { hdr = m; warned = 1 } else if (hdr == "") hdr = m
        if (m ~ /Call [Tt]race:/) stk = 1
        if (m !~ /^Modules linked in:/ && m !~ /(^| )x[0-9]+ *: [0-9a-f]+/) buf = buf "\n" m
    }
    m ~ /---\[ end trace/ { close_block() }
    END {
        close_block()
        if (fatal != "") print "FATAL " fatal
        if (gpu != "") print "GPU " gpu
        print "UNRELATED " n + 0
    }' <<<"$DMESG"
}
check_no_oops() {
    dmesg_needed no-oops && return
    local out fatal gpu n
    out=$(scan_traces)
    fatal=$(sed -n 's/^FATAL //p' <<<"$out")
    gpu=$(sed -n 's/^GPU //p' <<<"$out")
    n=$(sed -n 's/^UNRELATED //p' <<<"$out")
    if [ -n "$fatal" ]; then
        report FAIL no-oops "$fatal"
    elif [ -n "$gpu" ]; then
        report FAIL no-oops "gpu warning: $gpu"
    else
        report PASS no-oops none
    fi
    if [ "${n:-0}" -gt 0 ]; then report INFO unrelated-warnings "$n"; fi
}
check_no_minus19() {
    dmesg_needed no-minus19 && return
    verdict no-minus19 none "Couldn't power up the GPU" dm_lacks "Couldn't power up the GPU"
}
check_no_gx_warn() {
    dmesg_needed no-gx-warn && return
    verdict no-gx-warn none "GX power domain not available" dm_lacks "GX power domain not available"
}
check_renderer() {
    local e
    if [ -n "${EGLINFO_FILE:-}" ]; then e=$(cat "$EGLINFO_FILE" 2>/dev/null); else e=$(eglinfo -B 2>/dev/null); fi
    # Mesa reports "Adreno (TM) 830" (older builds: "FD830"); any llvmpipe/softpipe renderer fails
    if grep -qiE 'renderer: .*(llvmpipe|softpipe|swrast)' <<<"$e"; then
        report FAIL renderer "software renderer in eglinfo -B"
    else
        verdict renderer "Adreno 830" "no Adreno 830 renderer in eglinfo -B" grep -qE 'renderer: .*(Adreno \(TM\) 830|FD830)' <<<"$e"
    fi
}
check_zap() {
    dmesg_needed zap && return
    local l; l=$(grep -Em1 'pas_init_image' <<<"$DMESG")
    verdict zap "no pas_init_image error" "$l" [ -z "$l" ]
}
check_fuse() {
    local f v
    f=$(ls "$SYSROOT"/sys/bus/nvmem/devices/qfprom*/nvmem 2>/dev/null | head -1)
    if [ -z "$f" ]; then report INFO fuse "speed_bin absent (no qfprom nvmem)"; return; fi
    v=$(dd if="$f" bs=1 skip=$((0x138)) count=4 2>/dev/null | od -An -tx1 | tr -d ' \n')
    report INFO fuse "speed_bin@0x138=${v:-unreadable}"
}
pstore_ok() { [ -d "$SYSROOT/sys/fs/pstore" ] && dm_has "Registered ramoops"; }
check_pstore() {
    verdict pstore "ramoops registered" "pstore dir or 'Registered ramoops' missing" pstore_ok
}
check_hung_task() {
    local f=$SYSROOT/proc/sys/kernel/hung_task_timeout_secs
    verdict hung-task "$(cat "$f" 2>/dev/null)" "hung_task_timeout_secs missing" [ -e "$f" ]
}
zcat_has() { zcat "$1" 2>/dev/null | grep -q "$2"; }
check_dpm_watchdog() {
    local f=$SYSROOT/proc/config.gz
    if [ ! -r "$f" ]; then report INFO dpm-watchdog "config.gz unreadable"; return; fi
    verdict dpm-watchdog CONFIG_DPM_WATCHDOG=y "CONFIG_DPM_WATCHDOG not =y" \
        zcat_has "$f" "^CONFIG_DPM_WATCHDOG=y"
}
check_pon_reason() {
    if [ -n "$PON_REASON_PATH" ] && [ -r "$PON_REASON_PATH" ]; then
        report INFO pon-reason "$(tr -d '\n' <"$PON_REASON_PATH")"
    else
        report INFO pon-reason not-readable
    fi
}
check_suspend_hang_gpu() {
    dmesg_needed suspend-hang-gpu && return
    local l
    l=$(grep -E 'dpm_run_callback|DPM watchdog|dpm_watchdog|DPM device timeout|failed to (suspend|resume)' <<<"$DMESG" |
        grep -Em1 "(^|[ :])($GPU_PM_DEV_RE)([ :]|$)")
    verdict suspend-hang-gpu none "$l" [ -z "$l" ]
}
check_probe() {
    local r g
    r=$(link_target "$SYSROOT/sys/class/drm/renderD128/device/driver")
    g=$(link_target "$GPU_DIR/driver")
    verdict probe "renderD128=$r gpu=$g" "renderD128=${r:-none} gpu=${g:-none}" probe_ok "$r" "$g"
}
probe_ok() { { [ "$1" = msm_dpu ] || [ "$1" = msm ]; } && [ "$2" = adreno ]; }
check_pin_released() {
    local mode settle timeout limit waited=0 state=
    mode=$(sed -n 's/^MODE=//p' "$PIN_CONF" 2>/dev/null | tail -1)
    if [ "$mode" = always ]; then report INFO pin-released mode=always; return; fi
    settle=$(sed -n 's/^SETTLE=//p' "$PIN_CONF" 2>/dev/null | tail -1)
    timeout=$(sed -n 's/^TIMEOUT=//p' "$PIN_CONF" 2>/dev/null | tail -1)
    limit=${PIN_WAIT:-$(( ${settle:-15} + ${timeout:-180} ))}
    while :; do
        state=$(cat "$PIN_STATE" 2>/dev/null)
        [ "${state%% *}" = released ] && break
        [ "$waited" -ge "$limit" ] && break
        sleep 1; waited=$((waited + 1))
    done
    verdict pin-released released "state=${state:-missing} after ${waited}s" [ "${state%% *}" = released ]
}
maps_gpu_only() { grep -Eq "freedreno|libgallium" <<<"$1" && ! grep -Eq "llvmpipe|swrast" <<<"$1"; }
check_shell_on_gpu() {
    local pid=${MAPS_PID:-$(pidof gnome-shell | awk '{print $1}')} m
    m=$(cat "$SYSROOT/proc/${pid:-0}/maps" 2>/dev/null)
    verdict shell-on-gpu freedreno-or-libgallium "no GPU mesa mapped, or llvmpipe/swrast present (pid=${pid:-none})" \
        maps_gpu_only "$m"
}
check_runtime_suspends() {
    local ctl waited=0 st=
    ctl=$(cat "$GPU_DIR/power/control" 2>/dev/null)
    if [ "$ctl" = on ]; then report INFO runtime-suspends control=on; return; fi
    while :; do
        st=$(cat "$GPU_DIR/power/runtime_status" 2>/dev/null)
        [ "$st" = suspended ] && break
        [ "$waited" -ge "$SUSPEND_WAIT" ] && break
        sleep 1; waited=$((waited + 1))
    done
    verdict runtime-suspends suspended "runtime_status=${st:-missing} for ${waited}s" [ "$st" = suspended ]
}

g0() {
    load_dmesg
    check_gxclkctl_bound
    check_gmu_genpd
    check_gx_gdsc
    check_no_oops
    check_no_minus19
    check_no_gx_warn
    check_renderer
    check_zap
    check_fuse
    check_pstore
    check_hung_task
    check_dpm_watchdog
    check_pon_reason
    check_suspend_hang_gpu
    check_probe
    check_pin_released
    check_shell_on_gpu
    check_runtime_suspends
    exit "$failed"
}

cycles() {
    local secs=${1:-} rep=${TRACE_REPORT:-} tmp s r
    if [ -z "$rep" ]; then
        [ -n "$secs" ] || { echo "usage: $0 cycles <seconds>" >&2; exit 2; }
        command -v trace-cmd >/dev/null || { echo "cycles: trace-cmd not installed (run tablet/setup.sh)" >&2; exit 1; }
        tmp=$(mktemp -d) || exit 1
        trap 'rm -rf "$tmp"' EXIT
        trace-cmd record -o "$tmp/trace.dat" -b 4096 -e rpm:rpm_suspend -e rpm:rpm_resume \
            -f 'name == "3d00000.gpu"' sleep "$secs" >/dev/null || exit 1
        trace-cmd report -i "$tmp/trace.dat" >"$tmp/report.txt" || exit 1
        rep=$tmp/report.txt
    fi
    if [ ! -r "$rep" ]; then echo "cycles: trace report unreadable: $rep" >&2; exit 1; fi
    # rpm tracepoints print "<dev> flags-.." (accept "name=<dev>" too)
    s=$(grep -Ec "rpm_suspend: (name=)?$GPU_DEV_RE( |$)" "$rep")
    r=$(grep -Ec "rpm_resume: (name=)?$GPU_DEV_RE( |$)" "$rep")
    s=${s:-0}; r=${r:-0}
    echo "cycles=$(( s < r ? s : r )) suspend=$s resume=$r"
}

case "${1:-}" in
    g0) g0 ;;
    cycles) shift; cycles "$@" ;;
    *) echo "usage: $0 g0 | cycles <seconds>" >&2; exit 2 ;;
esac
