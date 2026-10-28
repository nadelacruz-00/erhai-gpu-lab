#!/bin/bash
# One-off diagnostic for the black screen on lab-60-gpu-reference* candidates: 90 s after
# boot, save display/GPU state to /var/lib/erhai-gpu/black-<boot8>/.
B=$(tr -d '-' < /proc/sys/kernel/random/boot_id)
D=/var/lib/erhai-gpu/black-${B:0:8}
mkdir -p "$D"
uname -r > "$D/kver.txt"
eglinfo -B > "$D/eglinfo-root.txt" 2>&1
# as the greeter user, against the running compositor
GDMUID=$(id -u gdm 2>/dev/null)
sudo -u gdm XDG_RUNTIME_DIR=/run/user/$GDMUID WAYLAND_DISPLAY=wayland-0 eglinfo -B > "$D/eglinfo-gdm.txt" 2>&1
for d in /sys/kernel/debug/dri/*; do echo "== $d $(cat $d/name 2>/dev/null)"; cat $d/state 2>/dev/null; done > "$D/drm-state.txt"
for d in /sys/kernel/debug/dri/*; do [ -r $d/gpu ] && { echo "== $d"; timeout 5 cat $d/gpu; }; done > "$D/dri-gpu.txt" 2>&1
grep . /sys/class/backlight/*/{brightness,actual_brightness,bl_power,max_brightness} > "$D/backlight.txt" 2>&1
grep . /sys/class/drm/card*-*/{status,enabled,dpms} > "$D/connectors.txt" 2>&1
cat /sys/kernel/debug/pm_genpd/pm_genpd_summary > "$D/genpd.txt" 2>&1
grep . /sys/devices/platform/soc@0/3d00000.gpu/power/{control,runtime_status} > "$D/gpu-rpm.txt" 2>&1
for p in $(pgrep -x gnome-shell); do echo "== $p $(tr '\0' ' ' < /proc/$p/cmdline)"; grep -oE '/[^ ]*(dri|gallium|freedreno|msm|llvmpipe|swrast)[^ ]*' /proc/$p/maps | sort -u; done > "$D/shell-maps.txt" 2>&1
journalctl -b --no-pager > "$D/journal.txt" 2>&1
echo done > "$D/DONE"
