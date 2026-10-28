# Ladder

Every hardware test of candidate `60-gpu-reference` is judged against this page: the baseline, the attribution rule, the rungs g-1..g4 plus the PR, and the bisection procedure. Source: the design doc (`nadelacruz-erhai-pps-dual-pump-design-20261027-171129.md`) with the eng-review ledger applied (D3 PON reason, D4 tools and inducer, D5 checker, D9 regression contract). g1's hang source is upstream IGT `msm_recovery` (2026-10-28: the D4 shader inducer never hung the GPU, see below). No cooling map (`62-gpu-cooling-map` is a TODO).

Instruments:

- `sudo tablet/gpu-checks.sh g0` prints one `PASS|FAIL|INFO` line per check and exits 1 on any FAIL (run it with sudo: `gx-gdsc-summary` reads debugfs). Check ids: `gxclkctl-bound`, `gmu-genpd`, `gx-gdsc-summary`, `no-oops`, `no-minus19`, `no-gx-warn`, `renderer`, `zap`, `fuse`, `pstore`, `hung-task`, `dpm-watchdog`, `pon-reason`, `suspend-hang-gpu`, `dmesg-readable`, `probe`, `pin-released`, `shell-on-gpu`, `runtime-suspends`; `no-oops` fails only on an Oops/BUG or a WARNING/Call trace naming the GPU, GMU, gdsc or gxclkctl, and other traces are counted in `INFO unrelated-warnings`.
- A DPM-watchdog panic reboots the tablet, so it shows up in the NEXT boot's pstore (`/sys/fs/pstore`, archived by `systemd-pstore` to `/var/lib/systemd/pstore`), not in g0's `journalctl -k -b`.
- `tablet/gpu-checks.sh cycles <seconds>` counts rpm suspend/resume cycles of `3d00000.gpu` over a window.
- `sudo erhai-gpu-lab setup` (once) installs the build dependencies and runs `igt-recovery build`, which clones igt-gpu-tools `v2.6` (`916c79cfb767`) into `/var/lib/erhai-gpu/igt` and builds only `msm_recovery`. `sudo tools/igt-recovery/igt-recovery run [gpu-fault|hangcheck]` runs one subtest, saves `journalctl -k` for the run to `/var/lib/erhai-gpu/g1-<subtest>-<ts>.txt` and prints `PASS|FAIL g1 <subtest>` from: IGT exit 0 (the 15 good submits replayed), exactly one `hangcheck recover!`, no `cx gdsc didn't collapse`, no hw_init/power-up error. Exit 0 PASS, 1 FAIL, 2 usage/setup. `gpu-fault` is the hardware hang-detect path; `hangcheck` disables the error IRQ (debugfs `disable_err_irq`) so the software hangcheck timer fires. These are the only hang sources; nothing else in this lab hangs the GPU on purpose. (Retired: `tools/gpu-hang`, the D4 shader inducer; on 2026-10-28 its default count completed in 0.020 s with no hang on `lab-43`, so it never exercised recovery.)
- `tools/export-patches.sh <kernel-dir> <branch> <candidate> [--prefix N]` exports the first N commits of the stack.
- `tablet/setup.sh` installs trace-cmd, mesa-utils, vulkan-tools and the IGT build dependencies (git, meson, ninja-build, libdrm-dev, libkmod-dev, libdw-dev, ...).

Preconditions for g0 on the candidate, g1 and g2: `/etc/erhai/gpu-pin.conf` has `MODE=once` (pin released). With `MODE=always` the checker reports `pin-released` as INFO and `runtime-suspends` as INFO (when `power/control=on`), which is not a proof. The one exception is the explicit `MODE=always` run in g1 recover.

## Runbook

The commands per rung, with the tablet's installed tool. Install `erhai-gpu-lab` once, then follow the lines in order. Every `erhai-gpu-lab` command that writes state or runs a tool needs `sudo`; `whoami`, `status`, `soak status` and `report` need no root. `tools/ship-candidate.sh` runs as the normal user (it calls `sudo` itself for `fetch` and `queue`).

1. Once: `sudo tablet/install.sh && sudo erhai-gpu-lab setup`. `setup` installs the g1 tools and builds IGT `msm_recovery` under `/var/lib/erhai-gpu/igt`. `install.sh` enables the boot service, which logs every boot to `/var/lib/erhai-gpu/boots.log` with `prev=clean|warm|cold|none|unknown` and runs a queued g0. `prev` says how the previous boot ended, classified as in the PON section: `clean`, `warm` or `cold`; `prev=none` means no previous boot is logged in the journal, so there is nothing to classify; `prev=unknown` means at least one boot came in between that the boot service never logged (it froze before `graphical.target`): the line names those boots as `unlogged=<boot8>,...` and the soak counts each as a reset.
2. g0 candidate: from the lab repo on `main`, as the normal user, `tools/ship-candidate.sh ~/Development/oneplus-erhai-linux erhai-gpu-reference 60-gpu-reference` exports the patches, pushes, waits for CI, runs `sudo erhai-gpu-lab fetch` for the release of the run it watched (`lab-<candidate>-<run>`) and queues the g0 check for that kernel. Prerequisites: `gh auth login`, and a clean tree outside `candidates/<candidate>/` (it refuses to commit other changes). Then reboot and pick the kernel in rEFInd; the boot service runs the queued g0 and `erhai-gpu-lab status` shows it. Run it from `main` because `kernel.yml` triggers only on pushes to `main` that touch `candidates/`, `ci/` or `kernel.yml`. It refuses to run without an `origin` remote, so publishing the lab repo (`gh repo create`) is a one-time prerequisite and the operator's decision. Local alternative (no push, no CI wait): export the patches with `tools/export-patches.sh`, then `tools/build-local.sh <candidate>` (live progress every 2 s), `sudo erhai-gpu-lab fetch <candidate> --from-dir out/<candidate>` and the queue line below. A full-clock build is a heavy SoC load: on 2026-10-28 the GMU wedged about 10 s into one on `lab-43` (Results), so run it from an SSH session. To queue by hand: `sudo erhai-gpu-lab queue g0 --expect <candidate|package>` (g0 is the only rung that runs at boot). A queued g0 runs only if the booted kernel matches `--expect`, otherwise the queue is kept for a later boot. The queue is consumed before g0 starts, so a reset during g0 does not re-run it.
3. g1 control, on the current `lab-43` kernel (or the package kernel) with `MODE=once`: `sudo erhai-gpu-lab g1 --runs 1 --hangcheck 0`. g1 prints a warning and waits until you type `yes`; `--yes` skips the prompt.
4. g1 candidate, after booting `60-gpu-reference` with `MODE=once`: `sudo erhai-gpu-lab g1` (5 `gpu-fault` runs, then 1 `hangcheck`). Then `sudo erhai-gpu-lab mode always`, reboot into the same kernel, `sudo erhai-gpu-lab g1 --pinned` (1 `gpu-fault` run with the pin active), then `sudo erhai-gpu-lab mode once` and reboot to release the pin again. `mode` takes effect at the next boot.
5. g2 soak: `sudo erhai-gpu-lab soak start`, use the tablet normally for 8 h or more (reboots and resets are counted), check with `erhai-gpu-lab soak status` (hours, cycles, boots, resets and GPU wedge lines), then `sudo erhai-gpu-lab soak stop`. `soak stop` closes the window: boots after it are not part of the soak, `soak status` says `stopped`, and the timer is disabled. `soak start` refuses while a soak runs (stop it first). The soak timer never runs g1.
6. g4 power: `sudo erhai-gpu-lab power` samples the battery V×I while idle on battery for 30 minutes and compares the average with the 3639 mW baseline (`--minutes N` changes the window).
7. Results: `erhai-gpu-lab report [--out FILE]` prints Markdown of all evidence. Run it with `sudo` to include the soak wedge lines.

The kernel is always picked by hand in rEFInd: nothing in the lab changes the default boot entry, and `fetch` only writes `/boot/<kver>.efi` and `/usr/lib/modules/<kver>/`.

**g1 hangs the GPU on purpose (through `igt-recovery run`) and is the only command that does.** `boot-run` and the soak timer never run it. On a kernel whose recovery is broken the screen freezes and a hard reset (power-key hold) is needed: keep an SSH session open and capture `journalctl -k` before resetting. g1 writes `/var/lib/erhai-gpu/g1-summary-<kver>-<boot8>.txt` incrementally (`<boot8>` is the first 8 characters of the boot id); a later g1 in the same boot writes `g1-summary-<kver>-<boot8>-2.txt`, `-3.txt` and so on, never over an earlier one. A summary with no `RESULT` line means the run froze or was interrupted; read it after the reboot.

## Baseline

Only the GMU-attributed column is this work's problem. The other-lane column belongs to the display and suspend work. Boots are keyed by journal start time (`journalctl --list-boots`); the boot ID is given where it was captured, since relative indices shift at every reboot. Indicative census, not a rate study.

| Period | Boots | GMU-attributed wedges (dmesg has `GMU OOB`/`hangcheck recover`/`a8xx_recover`) | Other-lane freezes, with evidence | Unattributed (no evidence either way) |
|---|---|---|---|---|
| Pinned, 2026-10-20 16:32 -> 10-24 18:37 | 45 | 1: boot of 10-23 03:01 (195 OOB wedges, 125 recovers, pinned) | 5: 10-21 20:07 (panel-off/power-key path), 10-21 21:12, 21:24, 21:47 (lab-00-debug suspend work), 10-22 07:03 (hung entering s2idle) | 0 |
| Pin-once, 10-24 18:37 -> 10-27 16:07 | 16 | 2: 10-27 15:22 (`3b74091312d9`, 53 wedges, 29 recovers, rebooted from SSH) and 10-27 15:35 (`c2a246527422`, the live capture, 194 recovers) | 2: 10-26 10:51 (`01d4eb650bd4`, charger attach/detach cycling in the last 90 s), 10-27 11:06 (`c248d5bb04ff`, DPU `vblank timeout`, gnome-shell unresponsive, no GMU lines) | 2: 10-27 12:59 (`ec0c5e40ecd6`) and 14:23 (`49ad13244063`), no GPU, DPU, suspend or hung-task lines before the hard reset; CPU at 101-103 C in the last seconds of both |

**Unattributed baseline: 2 in 16 boots** over ~3 days on the current IFPC-off kernel (`lab-43-pr-dual-pump`, pin-once). Any unattributed reset on the candidate is compared against this (clause 3). The baseline is written here before g0 (clause 3a).

## Attribution rule

Applies to every rung and to the Success Criteria.

1. A freeze or hard reset counts against this work ("GMU-attributed") if dmesg shows GMU/hangcheck/`a8xx_recover` lines before it, or `pm_genpd_summary` taken during it shows the GPU or GMU holding CX.
2. It is logged under "other lane" and does not fail the rung if the evidence names something other than the GPU: DPU `vblank timeout`/commit timeouts; a suspend-entry or resume hang whose DPM-watchdog or `PM:` callback line names a non-GPU device; a hung-task or softlockup trace whose stack is in a non-GPU driver; or a pstore/ramoops panic record from another subsystem. A DPM-watchdog panic, hung-task trace or softlockup that names `3d00000.gpu`, `3d37000.gmu`, `a6xx_*`/`a8xx_*` or `msm_gpu_*` is clause 1, not clause 2 (patch 5 puts `a6xx_rpmh_stop`/`a6xx_gmu_rpmh_off` back on the suspend path, so a GPU suspend hang is a possible outcome of this work).
3. A spontaneous reset or freeze with **no evidence either way** (no GPU lines, no DPU/suspend lines, no hung-task or softlockup trace, no pstore record) is scored **"unattributed" and counts against the rung**. Re-enabling IFPC (patch 5) is a change that could produce a silent power-on-reset with an empty log (the port disabled IFPC after one such event on 2026-09-12), but the current IFPC-off kernel already produces them (baseline above: 2 in 16 boots, both on 10-27 with the CPU at 101-103 C). Protocol:
   - (a) the baseline is written into `docs/ladder.md` before g0;
   - (b) an unattributed reset in g2/g4 first gets its evidence paths checked: was `/sys/fs/pstore` populated after the reboot? did `systemd-pstore` archive to `/var/lib/systemd/pstore`? was the hung-task detector armed (`/proc/sys/kernel/hung_task_timeout_secs`)?
   - (c) if the paths worked and the log is still empty, run the A/B: re-apply only the IFPC revert (`9c3aa45c45`), rebuild as `60-gpu-reference-ifpc-off`, run the same rung for the same wall-clock time, and compare counts against each other and against the baseline;
   - (d) IFPC stays off only if the IFPC-on arm shows more unattributed resets than both the IFPC-off arm and the baseline over equal time; otherwise the resets are logged as a pre-existing lane (thermal or other) and the rung is judged on clauses 1 and 2. One event never decides it.

**Evidence paths that make clause 3 rare.** The lab kernel builds hung-task, softlockup and DPM-watchdog detection (patch 6). The kernel has `CONFIG_PSTORE=y`, `PSTORE_RAM=y`, `PSTORE_CONSOLE=y` with the `ramoops@a7800000` reserved-memory node registered (`pstore: Registered ramoops as persistent store backend` in every boot) and `/sys/fs/pstore` mounted.

**Limit (eng review D3).** On this board ramoops survives only a warm reset, i.e. a kernel-driven reboot such as the `panic=30` path. A PMIC-watchdog reset or a power-key hold does not preserve DRAM (`dc13a4717c`, 2026-08-28, re-added `af94396238`). So a hung-task/softlockup/DPM-watchdog *panic* leaves a record, but a PMIC watchdog bite or a thumb on the power key leaves nothing. Do not read a cold reset as "pstore silent".

**PON reason: no reason code, but warm vs cold is readable (probe 2026-10-28, see Results).** The SDAM `restart_reason` byte (`spmi_sdam0` offset `0x48`) reads `00` after both a software reboot and a power-key hold, so Linux cannot tell a PMIC-watchdog reset from a power-key hold. A cold (PMIC) reset does wipe SDAM `0x50-0x5b`, which holds the RTC offset, so the next boot starts at 1970 and the journal shows `erhai-rtc-sync: system clock is 1970-… -- refusing to store it`. A warm reboot (including a `panic=30` reboot) keeps the offset. Clause 3 therefore classifies an empty-log reset as **cold** (PMIC watchdog or power key: indistinguishable) when the following boot's journal has that rtc-sync line, else **warm** (expect a pstore record). `pon-reason` in g0 stays `INFO not-readable`.

## Rungs

**Two recovery paths, two proofs.** A CP hang (IGT `msm_recovery`) reaches `a8xx_recover` with `gmu->hung == false`: `a6xx_gmu_stop` runs the graceful `a6xx_gmu_shutdown`, the GMU itself drops GX, and `a6xx_gmu_gxpd_put` only forces GX if `gx_is_on()` still reads true. A GMU wedge (OOB/HFI timeout, `a6xx_gmu_fault`) sets `gmu->hung = true`: `a6xx_gmu_force_off` runs, `gx_is_on()` is true, and `a6xx_gmu_gxpd_put` -> `dev_pm_genpd_synced_poweroff(gxpd)` is the only thing that drops GX so CX can collapse. P1a is about the second path. There is no clean way to induce a GMU wedge from userspace, so g1 proves the recovery machinery is present and healthy with a control run, and the P1a proof itself rests on the first natural wedge in g2/g4. P1a log sequence: `GMU OOB`/`HFI` timeout -> one `hangcheck recover!` -> no `cx gdsc didn't collapse` -> `hw_init` succeeds -> fences resume.

| Rung | What | Pass |
|---|---|---|
| g-1 fuse | **Never read the fuse through `/dev/mem` (`devmem2`): on this SoC the qfprom region is firewalled and the read reset the tablet on 2026-10-28.** The running package kernel has no qfprom nvmem node, so the value is read on the candidate (which adds `efuse@221c8000` with `gpu-speed-bin@138`): `sudo tablet/gpu-checks.sh g0` prints `INFO fuse speed_bin@0x138=<value>`, and the adreno driver logs the bin it picked. Mask `& 0x1ff` (9 bits from bit 0). | Value recorded at g0. If it is not one of `0, 252, 242, 232, 221, 190`, the GPU does not probe on the candidate (g0 `probe`/`renderer` FAIL, desktop on llvmpipe): reboot to the package kernel and add one commit to patch 4 mapping that value to a bin with the OPP mask argued from Qualcomm's table; report the value in the TheMojoMan issue. |
| g0 control | Same `sudo tablet/gpu-checks.sh g0` on the package kernel first (D9 control row). Needs `MODE=once`. | Preserved behaviors (1)-(5) below all PASS, `-19` present, `genpd:1` absent. Recorded in Results before the candidate's g0. This proves the checker before it judges the candidate. |
| g0 boot | Boot `60-gpu-reference` (needs `MODE=once`, pin released); run `sudo tablet/gpu-checks.sh g0` | No FAIL. Preserved (D9): (1) `probe`: GPU probes without `erhai_gmu_enable`, `/dev/dri/renderD128` driver `msm`, no `Couldn't power up the GPU` line; (2) `zap`: auth OK, no `pas_init_image`/zap error; (3) `renderer`: `eglinfo -B` reports `FD830`; (4) `pin-released`: `erhai-gpu-pin-once` reaches `RELEASED` (`/run/erhai-gpu-pin-once.state`, wait <= SETTLE+TIMEOUT); (5) `shell-on-gpu`: gnome-shell maps freedreno/`libgallium`, not `llvmpipe`/`swrast`. Intentional changes: `no-minus19` (no `-19` at boot); `gmu-genpd` (a `*.gmu` device, `3d37000.gmu` today, has `genpd:0` and `genpd:1`; the line names it); `runtime-suspends` (`runtime_status` of `3d00000.gpu` reaches `suspended` at least once in 60 s idle with `control=auto`). Also: `gxclkctl-bound` (`3d64000.clock-controller/driver` -> `gxclkctl-kaanapali`); `gx-gdsc-summary` (`sudo cat /sys/kernel/debug/pm_genpd/pm_genpd_summary` lists `gx_clkctl_gx_gdsc` with the GMU); `no-oops`; `no-gx-warn` (the patch-7 `dev_warn` is absent); `fuse` (speed_bin and enabled OPPs via `available_frequencies`); evidence paths `pstore`, `hung-task`, `dpm-watchdog` (`grep DPM_WATCHDOG /proc/config.gz` = y); `pon-reason` (D3); `suspend-hang-gpu`, `dmesg-readable` (a dmesg that cannot be read fails the absence checks). |
| g1 control | On the current `lab-43` kernel (or the package kernel), `control=auto`, `MODE=once`: run `sudo tools/igt-recovery/igt-recovery run gpu-fault` once. **WARNING: on a kernel whose recovery is broken the screen will freeze and a hard reset (power-key hold) is needed. Keep an SSH session open and capture `journalctl -k` before resetting.** It may also recover cleanly; record which. Record dmesg. | Outcome recorded either way: infinite loop (today's freeze) or clean recovery. If the control recovers, g1 on the candidate shows only "the CP-hang path still works" and P1a's proof moves to the first natural wedge in g2/g4. |
| g1 recover | On `60-gpu-reference`, `control=auto`, `MODE=once`: run `sudo tools/igt-recovery/igt-recovery run gpu-fault` 5 separate times, then `run hangcheck` once. Then `run gpu-fault` once more with the pin active (`MODE=always`), so the rollback configuration is also shown to recover. | Each run: `PASS g1 <subtest>` (IGT exit 0, exactly one `hangcheck recover!`, no `cx gdsc didn't collapse`, no hw_init error), the desktop continues (gnome-shell keeps committing); a devcoredump with the GMU log exists if gen8 dumps are wired. IGT killed by the 120 s timeout, `recover` > 1 (a loop) or a frozen screen is a FAIL. |
| g2 soak | 8 h of normal use with `control=auto` (`MODE=once`); count rpm cycles with `tablet/gpu-checks.sh cycles <seconds>` (trace-cmd `-b 4096` with a `dev_name` filter on `3d00000.gpu`) | >= 1000 suspend/resume cycles; zero GMU-attributed wedges, or every wedge recovers with the P1a log sequence (that first recovered natural wedge is the P1a proof). Record the cycle count at any wedge (hypothesis (i) stale RPMh/PDC state vs (ii) ungated OPPs). |
| g3 Fmax | Only if g2 wedges: cap `max_freq` to 967 MHz, then 900 MHz, from userspace; compare wedge rate; relate to the fuse bin and `opp-supported-hw` | Wedge-rate difference across >= 8 h each; decides whether bin gating is the trigger. |
| g4 daily | 48 h daily use, pen, Krita, video, docked DP if available. Idle power (below). | No GMU-attributed or unattributed hard reset (attribution rule); wedges, if any, all recovered with the P1a log sequence. Idle power: candidate <= baseline. |
| PR | Issue on TheMojoMan/oneplus-erhai-linux first, then PR to `7.3-rc5` with the ladder numbers | Accepted or explicit feedback. If no natural GMU wedge occurred in g2 + g4, the PR claims what was shown: the two window fixes, the GX genpd attached (g0), the restored RSCC/rpmh paths, CP-hang recovery (g1 logs), and marks "GMU-wedge recovery not yet observed on this unit"; the issue asks TheMojoMan and yzddmr6 for a wedge log from the new stack. Candidate `61-gpu-no-scm-init` runs after the PR is opened; its result goes into the issue, not into the series. |

**Idle-power method (g4).** Screen on at a fixed brightness, Wi-Fi on, no apps, 30 min. Read `energy_now` (or `charge_now * voltage_now`) from `/sys/class/power_supply/erhai-adsp-bat/` at start and end; mW = delta / 0.5 h, converted to the same units. Measured once on the pinned package kernel (baseline, recorded here before g0) and once on the candidate with `control=auto`.

## Bisection

The candidate is an ordered stack of 13 commits, bottom to top:

1. DT providers (gxclkctl `3d64000`, gpucc, adreno_smmu)
2. revert of `9c9eefdef1` (gxclkctl un-bind)
3. Qualcomm GPU/GMU nodes
4. A830 catalog
5. defconfig `SM_GPUCC_8750=y`
6. `dev_warn` on GX attach failure (D6)
7. revert `66500d1eef`
8. revert `e9faa3ec42`
9. revert `cbfce58e8e`
10. revert `ef4d9b41ae`
11. gate + `rpmh_off` removal
12. revert `992da703ed` (cold boot)
13. revert `9c3aa45c45` (IFPC)

Commits 3 and 4 move together (the catalog's GEN1 entry and the DT reg sizes are one change; the OPP table needs the qfprom cell from the same patch). `extra.config` sets `CONFIG_SM_GPUCC_8750=y` for every prefix build, including `--prefix 2`.

Every prefix build goes to its own candidate dir, so `60-gpu-reference` always holds the full stack: `tools/export-patches.sh <kernel-dir> erhai-gpu-reference 60-gpu-reference-pN --prefix N`. A new dir gets `60-gpu-reference`'s `cmdline` and `extra.config`; `STACK` records the exported tip and CI puts its first 12 hex digits on the UKI cmdline (`erhai_lab.stack=`) and in the release notes, so `erhai-gpu-lab whoami` shows which stack booted. Order, each expected to boot:

- `60-gpu-reference-p2` (`--prefix 2`): providers + gxclkctl bound; the port's GPU/GMU nodes and catalog unchanged. Must boot and show the GX genpd attached.
- `60-gpu-reference-p6` (`--prefix 6`): plus Qualcomm's GPU/GMU nodes and catalog, defconfig and `dev_warn`; the port's GMU hacks still present. Must boot the GPU.
- `60-gpu-reference-p12` (`--prefix 12`): the candidate minus IFPC (7-10 reverts and the gate removal included).
- `60-gpu-reference-p11` (`--prefix 11`): minus IFPC and cold boot.
- `60-gpu-reference-p10` (`--prefix 10`): minus IFPC, cold boot and the gate/`rpmh_off` removal.
- `60-gpu-reference` (no `--prefix`): the full stack (13), the candidate.
- A/B arm (clause 3c): `tools/export-patches.sh <kernel-dir> erhai-gpu-reference 60-gpu-reference-ifpc-off --prefix 12`.

Reading the results:

- If g0 fails at prefix 2, the fault is in the provider nodes or the bound gxclkctl itself; approach A's content (windows only, port catalog kept) is the fallback PR.
- If prefix 2 boots and prefix 6 does not, the fault is in the reference GPU/GMU/catalog adoption; restore the port's nodes one node at a time (GMU node first, then catalog).
- If prefix 6 boots and the full stack does not, drop from the top one prefix at a time: 12 (IFPC), then 11 (cold boot), then 10 (gate).
- If g0 passes but g1 fails, re-apply only `e9faa3ec42` to confirm RSCC is the lever.
- Unattributed resets: follow clause 3 (A/B with `60-gpu-reference-ifpc-off`, which is `--prefix 12` in its own dir).

## Results

Fill from the tablet. Paste command output verbatim.

### g-1 fuse (operator step, not run)

| Field | Value |
|---|---|
| Kernel | |
| Date | |
| Raw (`INFO fuse` line from g0 on the candidate) | |
| Masked (`& 0x1ff`) | |
| In `0, 252, 242, 232, 221, 190`? | |
| Action | |

Read on the candidate only (never `devmem2`): the `INFO fuse` line of `sudo tablet/gpu-checks.sh g0`. The DT cell is `gpu-speed-bin@138 { reg = <0x138 0x2>; bits = <0 9>; }` (nvmem `bits = <offset nbits>`: 9 bits from bit 0), so `speed_bin = value & 0x1ff`. If not in the table, go back to Task 3 step 10 for the mapping commit.

### PON reason probe (Task 9)

Done 2026-10-28 (package kernel `lab-43`). The nvmem node rejects whole-block reads (`EINVAL`); read it one byte at a time, no sudo needed:

```
F=/sys/bus/nvmem/devices/spmi_sdam0/nvmem
for o in $(seq $((0x40)) $((0x7f))); do printf '%02x %s\n' $o "$(dd if=$F bs=1 skip=$o count=1 status=none | od -An -tx1 | tr -d ' ')"; done
```

| Byte | After software reboot | After power-key hold | Meaning |
|---|---|---|---|
| `0x48` (`restart_reason`) | `00` | `00` | no reason code |
| `0x50-0x53` (`rtc-offset`) | `3b d6 fd 69` | `00 00 00 00` | wiped by a cold reset (clock starts at 1970; rtc-sync refuses to store it) |
| `0x5a-0x5b` | `92 0b` | `00 00` | wiped by a cold reset |
| `0x5e-0x5f` | `fe 21` | `88 1a` | changes every boot; not a reason code |

Result: power key vs PMIC watchdog is not distinguishable from Linux; warm vs cold is (rtc-offset wiped, or `erhai-rtc-sync: system clock is 1970` in the next boot's journal). Evidence: `~/gpu-lab-evidence/sdam0-after-reboot-*.txt`, `sdam0-after-powerkey-*.txt`.

### g0 control (package kernel `7.3.0-rc5-sm8750-themojoman-lab-43-pr-dual-pump`, 2026-10-28, `MODE=once`)

Command: `sudo tablet/gpu-checks.sh g0 | tee g0-control.txt` on the package kernel with `MODE=once`. Paste below. Expect (1)-(5) PASS, `-19` present, `genpd:1` absent. `hung-task` and `dpm-watchdog` FAIL here by design (those detectors are lab-only `extra.config` options, absent from the package kernel).

```
FAIL gxclkctl-bound driver=none
FAIL gmu-genpd genpd:1 missing for 3d6a000.gmu
FAIL gx-gdsc-summary gx_clkctl_gx_gdsc not in pm_genpd_summary
PASS no-oops none
INFO unrelated-warnings 13
FAIL no-minus19 Couldn't power up the GPU
PASS no-gx-warn none
PASS renderer Adreno 830   # re-run after the renderer-check fix; first run said FAIL (checker looked for "FD830")
PASS zap no pas_init_image error
INFO fuse speed_bin absent (no qfprom nvmem)
PASS pstore ramoops registered
FAIL hung-task hung_task_timeout_secs missing
FAIL dpm-watchdog CONFIG_DPM_WATCHDOG not =y
INFO pon-reason not-readable
PASS suspend-hang-gpu none
PASS probe renderD128=msm_dpu gpu=adreno
PASS pin-released released
PASS shell-on-gpu freedreno-or-libgallium
PASS runtime-suspends suspended
```

Verdict: as expected. Contract (1)-(5) PASS (`probe`, `zap`, `renderer`, `pin-released`, `shell-on-gpu`); the bug is visible (`gxclkctl-bound` driver=none, `gmu-genpd` genpd:1 missing for 3d6a000.gmu, `gx-gdsc-summary` absent, `-19` at GPU load); `runtime-suspends` PASS with the pin released.

### g1 control (`lab-43`, 2026-10-28, `MODE=once`, `control=auto`)

`sudo erhai-gpu-lab g1 --runs 1 --hangcheck 0` → `PASS g1 gpu-fault` (IGT `Subtest gpu-fault: SUCCESS (6.057s)`, recover=1, cx_not_collapsed=0, hw_init_errors=0). Evidence: `~/gpu-lab-evidence/g1-gpu-fault-20261028-183619.txt`, `g1-summary-7.3.0-rc5-sm8750-themojoman-lab-43-pr-dual-pump-f78af4d1.txt`.

```
18:36:24 hangcheck_handler *ERROR* 44050031: hangcheck detected gpu lockup rb 0!   (completed 152364, submitted 152372)
18:36:24 recover_worker    *ERROR* 44050031: hangcheck recover!   offending task: msm_recovery --run-subtest gpu-fault
18:36:25 [IGT] msm_recovery: finished subtest gpu-fault, SUCCESS
```

Reading: the CP-hang path recovers cleanly on today's kernel. The hang was caught by the software hangcheck timer about 5 s after submit; there was no hardware error IRQ for the bad packet. No GMU OOB/HFI line, no `cx gdsc didn't collapse`, and the 15 good submits were replayed. This is the "control recovers" branch of the g1 control row. On the candidate, g1 therefore only shows that the CP-hang path still works, and the P1a proof (GMU-wedge recovery through the forced GX collapse) rests on the first natural wedge in g2/g4. This matches the design: a CP hang leaves `gmu->hung == false`, so the graceful GMU shutdown drops GX without the missing GX genpd.

### Natural GMU wedge on `lab-43` during a full-clock build (2026-10-28 19:08:11, `MODE=once`, `control=auto`)

Load: `ci/build-candidate.sh` run locally on 8 cores, with the CPU caps lifted to the hardware max (3.53/4.09 GHz) and the governor set to `performance`. Evidence: `~/gpu-lab-evidence/freeze-during-build-191100.txt` (kernel log), `freeze-during-build-thermal.log` (5 s samples).

```
[8061.542] a6xx_gmu_set_oob erhai: GMU OOB set GPU_SET attempt 1/3 timed out, retrying
[8061.562] a6xx_gmu_set_oob *ERROR* Timeout waiting for GMU OOB set GPU_SET: 0x0
[8061.562] a6xx_gmu_set_oob erhai: GMU OOB set GPU_SET wedged after 3 attempts - escalating to full GPU recovery
[8061.593] recover_worker *ERROR* hangcheck recover!
(no further GPU lines; 3d00000.gpu runtime_status stuck at "resuming", screen frozen, SSH alive)
```

| t (epoch) | hottest CPU | cpu0 / cpu6 MHz | clamp c0/c1 |
|---|---|---|---|
| 1793185681 (build start) | 56 C | 3532 / 4089 | 0/0 |
| 1793185686 | 69 C | 3532 / 4089 | 0/0 |
| **1793185691 (wedge)** | 65 C | 2227 / 3072 | 6/6 |
| later peak | 98 C | 1363-1785 / 2246-2649 | 8-10 |

Reading: GMU-attributed (clause 1), and the P1a failure seen live: recovery ran twice and then stopped, with no loop this time, and the GPU never came back. The trigger time is the new data point. The wedge came about 10 s into the load, at the first thermal clamp step (0 to 6) and the CPU's largest power step, at 65 C, not at the 98 C peak. That favours a power or rail transient over temperature as the wedge trigger (P1b), something g2/g4 on the candidate can try to reproduce: a burst of full-clock CPU load while the GPU is runtime-suspending or resuming.

### Black screen on 60-gpu-reference: GPU clock drivers built in (2026-10-28/29)

Symptom: with the full stack, the panel went fully dark (no backlight glow) right after rEFInd. Most boots froze before journald reached disk, with no panic, no pstore record and no network. The three boots that did reach userspace (24c0f462, 5e1d4fed, fa58bc06) logged 9-10 `arm-smmu 15000000.iommu: Unhandled context fault ... SID=0x800` (MDSS) at iova `0xfc8xxxxx` (the bootloader's splash framebuffer) as apps_smmu probed. lab-43 and package boots log 0.

Bisection (CI builds): p2 (patches 1-2) froze; nopd (gpucc without its MX/CX power-domains), devlink (no `fw_devlink=off`), mdssid (`qcom,sm8750-mdss` added to the SMMU identity list) and order (adreno_smmu after gpucc) all stayed black. The working kernels build `CONFIG_SM_GPUCC_8750=m`; every lab candidate built it `=y` (yzddmr6 `bd4f02e3f7`, carried as patch 5, plus this candidate's `extra.config`). That symbol builds both `gpucc-sm8750` and `gxclkctl-kaanapali`.

Fix: `60-gpu-reference-gpuccm` (full stack, `=m`) shows the desktop. SMMU faults: 0. gxclkctl bound, GMU `genpd:0`+`genpd:1`, no GX warning, GPU runtime-suspends with `control=auto`, renderer `Adreno (TM) 830`. The defconfig commit is dropped from `erhai-gpu-reference` (now 12 commits; the pre-change tip is kept as `erhai-gpu-reference-before-gpucc-m`). `extra.config` sets `=m`. Built in, the two drivers probe in the first second of boot with `fw_devlink=off` ordering nothing. Built as modules, they load from the root fs after their providers. The detailed mechanism (early gpucc/gxclkctl probe stalling the bus or yanking the splash scanout) is inferred, not traced.

Side finding: a local gcc-15 build (the package kernel b37) boots, so local builds are not inherently broken. The no-trace boots were this freeze, plus journald's 5-minute sync interval (`/etc/systemd/journald.conf.d/10-erhai-lab-sync.conf` now sets 10 s).

### g0 candidate (`60-gpu-reference-gpuccm` = the 12-commit stack with gpucc/gxclkctl as modules, local build, 2026-10-29, `MODE=once`)

`sudo gpu-checks.sh g0`: no FAIL. PASS gxclkctl-bound (`gxclkctl-kaanapali`), gmu-genpd (`3d37000.gmu genpd:0,genpd:1`), gx-gdsc-summary (`gx_clkctl_gx_gdsc`), no-oops, no-minus19, no-gx-warn, renderer (Adreno 830), zap, pstore, hung-task, dpm-watchdog, suspend-hang-gpu, probe, pin-released, shell-on-gpu, runtime-suspends. INFO: unrelated-warnings 13, fuse unreadable via nvmem, pon-reason not-readable. MDSS SMMU faults: 0. GPU OPPs available: 160-1100 MHz (14 levels), so the speed bin did not gate the GPU off (g-1 satisfied in practice; the raw fuse value stays unread). The first run of this checker reported `FAIL renderer`: a checker bug (root's `eglinfo -B` lists Mesa's llvmpipe in the Device-platform device list). Fixed in `288adae`.

### g1 recover on the candidate (`60-gpu-reference-gpuccm`, 2026-10-29 00:10-00:18, `MODE=once`, `control=auto`)

`sudo erhai-gpu-lab g1`: `gpu-fault` 5/5 **PASS** (IGT SUCCESS 6.9-7.9 s each, exactly one `hangcheck recover!`, no `cx gdsc didn't collapse`, no hw_init error, desktop kept running). `hangcheck` **FAIL**, reproduced twice: IGT `scratch[1+i] == 2+i` fails with `0 != 10` (submit #8 never ran) and `recover=2`. With the error IRQ off, the sw hangcheck fired after about 5 s and blamed fence 13743 (the oldest incomplete one, IGT submit #8; the bad packet is in #10), so recovery dropped an innocent submit. A second lockup was caught after IGT exited.

Control: the package kernel (`7.3.0-rc5-sm8750-themojoman`, b37, the old GPU stack) fails `hangcheck` identically (`0 != 10`, recover=2, 00:25). So this is a pre-existing a8xx sw-hangcheck blame/replay quirk, not something this candidate introduced. It is logged as other lane (an upstream drm/msm question), and g1 is judged on `gpu-fault`. Pinned run (`MODE=always`, `control=on`), first attempt on the 12-commit stack: froze. Every recovery logged `a8xx_recover: cx gdsc didn't collapse`, the same hang came back every 5 s (4 loops), then gnome-shell was blamed and a CP translation fault followed (`~/gpu-lab-evidence`, boot 78bdf0c9). Cause: a8xx_recover() resets the GPU by letting it runtime-suspend, and `power/control=on` forbids that. This is upstream drm/msm behaviour, so the `MODE=always` rollback has never survived a GPU hang. Fix: new commit 13 `drm/msm/a8xx: recover even when runtime PM is forbidden` (allow rpm for the reset, restore the forbid after). Rerun on the 13-commit stack (`60-gpu-reference`, local build, 00:47): **PASS** (IGT SUCCESS 6.6 s, one `hangcheck recover!`, no `cx gdsc didn't collapse`, `power/control` back to `on` afterwards).
Rerun with `MODE=once` on the 13-commit stack (00:50-00:53): `gpu-fault` **5/5 PASS** (6.5-7.0 s each, one recovery, no cx-collapse error, `control=auto`). g1 is complete.

### Idle-power baseline (operator step, not run)

Command, package kernel, screen on at fixed brightness, Wi-Fi on, no apps:

```
B=/sys/class/power_supply/erhai-adsp-bat
for i in $(seq 180); do echo "$(date +%s) $(cat $B/voltage_now) $(cat $B/current_now)"; sleep 10; done \
  | awk '{p=$2*$3/1e9; s+=(p<0?-p:p); n++} END {printf "avg %.0f mW over %d samples\n", s/n, n}'
```

(this battery exposes only `voltage_now` and `current_now`, so power is sampled as V×I)

| Kernel | Start | End | Delta | mW |
|---|---|---|---|---|
| package (baseline), lab-43, `MODE=once` | 1793177874 | 1793179672 | 180 samples, 4.24→4.17 V, 0.66-1.27 A discharge | **3639 mW avg** (`~/gpu-lab-evidence/idle-baseline.txt`, V×I every 10 s; this battery exposes no `energy_now`) |
| candidate, `control=auto` | | | | |

### Rung summary

| Rung | Kernel | Date | Result | Notes |
|---|---|---|---|---|
| g-1 | | | | |
| g0 control | lab-43 (package) | 2026-10-28 | as expected | renderer check fixed to accept `Adreno (TM) 830` |
| g0 | 60-gpu-reference (gpucc =m) | 2026-10-29 | PASS | all contract checks; GX genpd attached; black screen fixed by gpucc/gxclkctl =m |
| g1 control | lab-43 (package) | 2026-10-28 | PASS (recovered) | CP hang caught by the sw hangcheck in about 5 s, one `hangcheck recover!`; no GMU wedge path exercised |
| g1 recover (5x + MODE=always 1x) | 60-gpu-reference (gpucc =m, + rpm-forbidden recover fix) | 2026-10-29 | gpu-fault 5/5 PASS (12- and 13-commit stacks); pinned PASS after commit 13 | hangcheck subtest fails identically on the package kernel (pre-existing sw-hangcheck quirk) |
| g2 (cycles: ) | | | | |
| g3 | | | | |
| g4 (idle mW: ) | | | | |
| PR | | | | |
