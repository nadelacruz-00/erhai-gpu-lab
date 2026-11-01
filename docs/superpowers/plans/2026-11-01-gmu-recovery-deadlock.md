# GMU recovery deadlock fix + a8xx crash dumps — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A GMU wedge on the OnePlus Pad 3 (Adreno 830) costs a few seconds of recovery instead of a permanent freeze, and every wedge leaves a saved GPU crash dump.

**Architecture:**
- **Kernel** (three upstream-shaped patches plus one lab-only patch):
  - a `recovery_in_progress` guard that the GPU fault handler and the two GMU wait loops honor;
  - an async crash-state free that can't recurse on `gpu->lock`;
  - a shared a6xx snapshot helper that gives a8xx memory-only crash dumps.
- **Lab:**
  - a udev-started copier saves each GPU devcoredump to `/var/lib/erhai-gpu/coredumps/` and frees it;
  - `igt-recovery` (g1) checks the saved file;
  - candidate `71-a8xx-crashstate` is built locally first.

**Tech Stack:** Linux kernel C (drm/msm, 7.3-rc5), bash, Python 3 (unittest run via pytest), systemd + udev, IGT `msm_recovery` v2.6.

**Spec:** `~/.gstack/projects/TheMojoMan-oneplus-erhai-linux/nadelacruz-erhai-gpu-reference-design-20261101-193500.md` (Approach B, steps 1–2, as amended by its eng review: decision ledger R1–R9; tasks T1–T9). Test plan: `~/.gstack/projects/TheMojoMan-oneplus-erhai-linux/nadelacruz-erhai-gpu-reference-eng-review-test-plan-20261101-202429.md`.

## Global Constraints

- Kernel base: `origin/7.3-rc5` = `dbf6edb5ef38d6540c689cc6b0de8ad7b5ddca2a` (PR #9 merge), in TheMojoMan/oneplus-erhai-linux.
- Kernel builds are **local compile-first**: `tools/build-local.sh 71-a8xx-crashstate --kernel-dir <worktree>` on the tablet, then `sudo erhai-gpu-lab fetch 71-a8xx-crashstate --from-dir out/71-a8xx-crashstate`. GitHub CI runs only after a local build passes.
- Upstream-bound kernel commits carry **no AI trace**: author and `Signed-off-by: nadelacruz-00 <323917690+nadelacruz-00@users.noreply.github.com>` only. Lab-repo commits keep normal `Co-Authored-By`.
- Never use `/dev/mem` or `devmem2` on erhai. Never write a GPU-hang inducer; hangs come only from IGT `msm_recovery` (g1) and the natural repro (HDB 630 Bluetooth music). Never use `efibootmgr`; kernels are picked in rEFInd.
- a8xx crash dumps are **memory-only**: no MMIO register reads in the a8xx snapshot path.
- The a6xx/a7xx devcoredump output must not change (regression contract D7): the shared helper is a pure move plus one `bool gmu_regs` parameter.
- `/sys/class/devcoredump/disabled` is write-once (devcoredump.c:213): any test that writes 1 runs **last** in its boot.
- Do not start implementing until the user gives the go signal on this plan.

## Review Focus

1. **Other drivers' devcoredumps** (ath12k Wi-Fi, remoteproc ADSP/modem, the msm display snapshot) appear in `/sys/class/devcoredump` too. The copier must leave any devcd whose `failing_device` is not the GPU completely untouched: no copy and no free. Test in Task 5 (`test_non_gpu_devcd_is_untouched`).
2. **Two GPU dumps back to back** (a wedge storm: 12 recoveries in 28 min). Each copier run handles only its own `devcdN`, and file names don't collide when two dumps land in the same second. Test in Task 5 (`test_same_second_names_do_not_collide`).
3. **The copier started on a devcd that already vanished** (freed by timeout or another reader). It must exit cleanly without creating an empty `.bin`. Test in Task 5 (`test_missing_devcd_exits_quietly`).
4. **g1 on a kernel without a8xx dumps** (an older candidate or the package kernel). The dump check must fail with a message naming the missing `.bin`, not hang or pass. Test in Task 6 (`test_dump_check_reports_missing_bin`).
5. **A copier read blocked during a hung recovery** (eng review A-1). The service must not hold up boot or udev. The unit has no `[Install]`, is started only by udev and runs as `Type=oneshot`. Test in Task 5 (`test_unit_is_udev_started_oneshot`).

---

### Task 1: Kernel worktree + recovery guard flag (T1)

**Files:**
- Create: worktree `~/Development/erhai-gpu-71-wt` on new branch `erhai-gpu-recovery-deadlock` from `origin/7.3-rc5`
- Modify: `drivers/gpu/drm/msm/msm_gpu.h` (struct `msm_gpu`, next to `crashstate` at line 259)
- Modify: `drivers/gpu/drm/msm/msm_gpu.c` (`recover_worker`, lines 464–588)
- Modify: `drivers/gpu/drm/msm/adreno/adreno_gpu.c` (`do_devcoredump`, line 291)
- Modify: `drivers/gpu/drm/msm/adreno/a6xx_hfi.c` (wait loop, line 125)
- Modify: `drivers/gpu/drm/msm/adreno/a6xx_gmu.c` (OOB wait loop, line 435)

**Interfaces:**
- Produces: `bool recovery_in_progress;` in `struct msm_gpu`, written only by `recover_worker` while it holds `gpu->lock`, read with `READ_ONCE()` from other contexts.

Kernel paths here have no in-tree unit tests. Each kernel task is verified by a compile check plus checkpatch; behavior is proven on the device in Task 8.

- [ ] **Step 1: Create the worktree and build dir**

```bash
git -C ~/Development/oneplus-erhai-linux fetch origin 7.3-rc5
git -C ~/Development/oneplus-erhai-linux worktree add ~/Development/erhai-gpu-71-wt -b erhai-gpu-recovery-deadlock origin/7.3-rc5
make -C ~/Development/erhai-gpu-71-wt O=$HOME/Development/erhai-gpu-71-build erhai_defconfig
```
Expected: `git -C ~/Development/erhai-gpu-71-wt rev-parse HEAD` prints `dbf6edb5ef38d6540c689cc6b0de8ad7b5ddca2a`.

- [ ] **Step 2: Add the field and set/clear it in `recover_worker`**

In `struct msm_gpu`, add `bool recovery_in_progress;` with a comment: set by `recover_worker` under `gpu->lock` (fault capture and GMU waits must not wait on a fault dump during recovery). In `recover_worker`, `WRITE_ONCE(gpu->recovery_in_progress, true);` on the line right after `mutex_lock(&gpu->lock);` (msm_gpu.c:476), and `WRITE_ONCE(gpu->recovery_in_progress, false);` immediately before the single `mutex_unlock(&gpu->lock);` (msm_gpu.c:588, which every exit path reaches via `out_unlock`).

- [ ] **Step 3: Honor it in the fault handler and both wait loops**

- `adreno_fault_handler`: append `&& !READ_ONCE(gpu->recovery_in_progress)` to the `do_devcoredump` initializer (adreno_gpu.c:291-292).
- `a6xx_hfi_wait_for_msg_interrupt`: change `if (completion_done(&a6xx_gpu->base.fault_coredump_done)) break;` to also break when `READ_ONCE(a6xx_gpu->base.base.recovery_in_progress)`.
- `a6xx_gmu_set_oob`: the same change.
- Extend each loop's existing comment by one sentence: a fault dump can't complete while recovery holds `gpu->lock`.

- [ ] **Step 4: Compile and style check**

Run: `make -C ~/Development/erhai-gpu-71-wt O=$HOME/Development/erhai-gpu-71-build -j8 drivers/gpu/drm/msm/ 2>&1 | grep -E "error|warning: " ; echo rc=$?`
Expected: no `error`/`warning:` lines (grep rc=1).

- [ ] **Step 5: Commit (upstream style, no AI trace)**

```bash
cd ~/Development/erhai-gpu-71-wt && git add -A drivers/gpu/drm/msm
git commit -s -m "drm/msm: don't wait for a fault devcoredump during GPU recovery" -m "<body: the deadlock (adreno_fault_handler reinit_completion + mutex_lock(gpu->lock) vs recover_worker holding gpu->lock in a6xx_hfi_wait_for_msg_interrupt/a6xx_gmu_set_oob), the A830 evidence (recoveries with a CP page fault within 2 s: 3 of 3 stuck, without: 12 of 12 completed), Link to the July 2025 review https://www.mail-archive.com/freedreno@lists.freedesktop.org/msg39108.html>"
scripts/checkpatch.pl --strict -g HEAD
```
Expected: checkpatch `total: 0 errors, 0 warnings`.

---

### Task 2: Async crash-state free (T2)

**Files:**
- Modify: `drivers/gpu/drm/msm/msm_gpu.h` (struct `msm_gpu`)
- Modify: `drivers/gpu/drm/msm/msm_gpu.c` (`msm_gpu_devcoredump_free` line 214, `msm_gpu_init` line 888, `msm_gpu_cleanup` line 1042)

**Interfaces:**
- Consumes: `msm_gpu_crashstate_put(struct msm_gpu *gpu)` (msm_gpu.h:785, takes `gpu->lock`).
- Produces: `struct work_struct crashstate_free_work;` in `struct msm_gpu`; `static void msm_gpu_crashstate_free_worker(struct work_struct *work)` in msm_gpu.c.

- [ ] **Step 1: Add the work item**

`struct work_struct crashstate_free_work;` next to `crashstate` in `struct msm_gpu`. `msm_gpu_crashstate_free_worker()` uses `container_of(work, struct msm_gpu, crashstate_free_work)` and calls `msm_gpu_crashstate_put(gpu)`. `INIT_WORK(&gpu->crashstate_free_work, msm_gpu_crashstate_free_worker);` in `msm_gpu_init` next to `kthread_init_work(&gpu->recover_work, ...)` (line 914).

- [ ] **Step 2: Make the devcoredump free callback asynchronous**

`msm_gpu_devcoredump_free(void *data)` now only does `schedule_work(&gpu->crashstate_free_work);`. Comment: `dev_coredumpm()` calls this synchronously when it can't keep the dump (devcoredump disabled, or out of memory), while `msm_gpu_crashstate_capture()` holds `gpu->lock`.

- [ ] **Step 3: Flush on teardown**

In `msm_gpu_cleanup`, call `flush_work(&gpu->crashstate_free_work);` before the ringbuffers are destroyed (first statement after `DBG`).

- [ ] **Step 4: Compile and style check** (as in Task 1 Step 4)

Expected: no `error`/`warning:` lines.

- [ ] **Step 5: Commit**

Subject `drm/msm: free the crash state asynchronously`. Body: `msm_gpu_crashstate_capture()` → `dev_coredumpm()` → synchronous `free(data)` (devcoredump.c:371-379) → `msm_gpu_crashstate_put()` → `mutex_lock(&gpu->lock)` recursion; it happens on every recovery when `/sys/class/devcoredump/disabled` is 1. `git commit -s`, then `scripts/checkpatch.pl --strict -g HEAD` → 0 errors, 0 warnings.

---

### Task 3: Shared snapshot helper + a8xx crash dumps (T3)

**Files:**
- Modify: `drivers/gpu/drm/msm/adreno/a6xx_gpu_state.c` (`a6xx_gpu_state_get`, lines 1632–1658)
- Modify: `drivers/gpu/drm/msm/adreno/a6xx_gpu.h` (prototypes at lines 320–324)
- Modify: `drivers/gpu/drm/msm/adreno/a6xx_gpu.c` (`a8xx_gpu_funcs`, line 2934)

**Interfaces:**
- Produces: `static void a6xx_gpu_state_get_gmu(struct msm_gpu *gpu, struct a6xx_gpu_state *a6xx_state, bool gmu_regs)`; `struct msm_gpu_state *a8xx_gpu_state_get(struct msm_gpu *gpu)` (returns `ERR_PTR(-ENOMEM)` on allocation failure, like `a6xx_gpu_state_get`).
- Consumes: the existing `a6xx_gpu_state_put` and `a6xx_show`.

- [ ] **Step 1: Pure-move refactor**

Move `adreno_gpu_state_get(...)` and the `if (!adreno_has_gmu_wrapper(...) && !adreno_has_rgmu(...))` block (GMU register read, gmu log/hfi/debug BO snapshots, `a6xx_snapshot_gmu_hfi_history`) from `a6xx_gpu_state_get` into `a6xx_gpu_state_get_gmu()`. Wrap only the `a6xx_get_gmu_registers(gpu, a6xx_state);` call in `if (gmu_regs)`. `a6xx_gpu_state_get` calls it with `true` at the same point. The allocation and `INIT_LIST_HEAD` stay in the callers.

- [ ] **Step 2: Verify the move is pure (regression contract D7)**

Run: `cd ~/Development/erhai-gpu-71-wt && git diff --color-moved=dimmed-zebra -U0 drivers/gpu/drm/msm/adreno/a6xx_gpu_state.c`
Expected: every removed line reappears as a moved line, and the only new logic is `if (gmu_regs)` plus the helper's signature and call. Record the reviewed diff excerpt in the commit body.

- [ ] **Step 3: Add `a8xx_gpu_state_get` and wire the a8xx funcs**

`a8xx_gpu_state_get()`: `kzalloc_obj` + `INIT_LIST_HEAD(&a6xx_state->objs)`, `a6xx_gpu_state_get_gmu(gpu, a6xx_state, false)`, then `return &a6xx_state->base;`. No `gx_is_on` path and no register reads. The ring `rptr` comes from the memory shadow because A830 sets `ADRENO_QUIRK_HAS_HW_APRIV` (a6xx_gpu.c:2422). Add its prototype in a6xx_gpu.h next to `a6xx_gpu_state_get`. In `a8xx_gpu_funcs`, add `.show = a6xx_show,` and `.gpu_state_get = a8xx_gpu_state_get, .gpu_state_put = a6xx_gpu_state_put,`, each inside `#if defined(CONFIG_DRM_MSM_GPU_STATE)`, mirroring the a7xx tables (a6xx_gpu.c:2909–2918).

- [ ] **Step 4: Compile and style check** (as in Task 1 Step 4)

- [ ] **Step 5: Commit**

Subject `drm/msm/a8xx: add a memory-only GPU crash state`. Body: there was no `gpu_state_get` on a8xx, so no devcoredump was ever produced; the snapshot is memory-only; the D7 statement "a6xx/a7xx: build + pure-move review only, Tested-by welcome". `git commit -s`, then checkpatch → 0/0.

---

### Task 4: Lab-only capture-duration logging (T4)

**Files:**
- Modify: `drivers/gpu/drm/msm/msm_gpu.c` (`recover_worker` around line 530, `msm_gpu_fault_crashstate_capture` around line 620)

- [ ] **Step 1: Time both capture calls**

`ktime_get()` before and after each `msm_gpu_crashstate_capture(...)` call, then `dev_info(gpu->dev->dev, "erhai-lab: crashstate capture (%s) took %lld us\n", "recover" | "fault", ktime_us_delta(end, start));`.

- [ ] **Step 2: Compile check** (as in Task 1 Step 4)

- [ ] **Step 3: Commit as a separate, clearly lab-only patch**

Subject `LAB ONLY: drm/msm: log crash state capture durations`. Body: "not for upstream; input for the bounded-wait RFC (lab TODOS)". `git commit -s`.

---

### Task 5: GPU coredump copier, udev rule, service, install (T6)

**Files:**
- Create: `tablet/erhai-gpu-coredump` (bash, mode 0755)
- Create: `tablet/70-erhai-gpu-coredump.rules`
- Create: `tablet/erhai-gpu-coredump@.service`
- Modify: `tablet/install.sh`
- Create: `tests/test_coredump.py`
- Modify: `tests/test_install_docs.py`

**Interfaces:**
- Produces: `erhai-gpu-coredump <devcdN>`. Exit 0 = saved and freed, or not a GPU dump (untouched), or the devcd is gone. Exit 1 = copy failed (the dump was still freed, per D6). Exit 2 = usage error or a name not matching `^devcd[0-9]+$`. Output: `<boot8>-<epoch>[-N].bin`, mode 0600, in `$ERHAI_COREDUMP_DIR`. At most `$ERHAI_COREDUMP_KEEP` files are kept, oldest by mtime deleted first. Messages go to stderr with the prefix `erhai-gpu-coredump: `.
- Environment overrides (for tests), with these defaults:
  - `ERHAI_DEVCD_ROOT=/sys/class/devcoredump`
  - `ERHAI_COREDUMP_DIR=/var/lib/erhai-gpu/coredumps`
  - `ERHAI_BOOT_ID_FILE=/proc/sys/kernel/random/boot_id`
  - `ERHAI_COREDUMP_KEEP=20`
  - `ERHAI_GPU_DEVICE=3d00000.gpu` (compared with the basename of `readlink -f $ERHAI_DEVCD_ROOT/<devcdN>/failing_device`)
  - `ERHAI_NOW=$(date +%s)` (the epoch used in the file name)
- Task 6 consumes the output path pattern `$ERHAI_COREDUMP_DIR/*.bin`.

- [ ] **Step 1: Write the failing tests**

Add `tests/test_coredump.py`, a `unittest.TestCase` that builds a fake devcd root in a tempdir:
- `devcdN/data` is a regular file containing `ringbuffer:\ngmu-log:\n`;
- `devcdN/failing_device` is a symlink to a dir named `3d00000.gpu`;
- `boot_id` holds `01234567-89ab-cdef-0123-456789abcdef`.

It runs the script with `subprocess.run(["bash", script, name], env=...)`. Tests and assertions:
- `test_gpu_dump_is_saved_then_freed`: rc 0; exactly one `01234567-*.bin` with that content and mode `0o600`; `data` now reads `1` (the free write).
- `test_copy_failure_still_frees`: store dir chmod 0500; rc 1; stderr contains `erhai-gpu-coredump: copy failed`; no `*.bin` left; `data` reads `1`.
- `test_rotation_keeps_newest_20`: 20 pre-existing `.bin` files with mtimes 1..20 (os.utime); after a run there are 20 files, and the mtime-1 file is gone.
- `test_bad_name_is_rejected`: names `../x`, `devcdX` and `devcd1/../y` give rc 2, with no write anywhere.
- `test_non_gpu_devcd_is_untouched`: `failing_device` → a dir named `ath12k_pci`; rc 0; no `.bin`; `data` unchanged.
- `test_missing_devcd_exits_quietly`: name `devcd9` that doesn't exist; rc 0; no `.bin`.
- `test_same_second_names_do_not_collide`: two runs (devcd1, devcd2) with `date` fixed via `ERHAI_NOW=1793500000`; two distinct files, `01234567-1793500000.bin` and `01234567-1793500000-2.bin`.
- `test_unit_is_udev_started_oneshot`: the `.service` file has `Type=oneshot` and `ExecStart=/usr/local/lib/erhai-gpu-lab/erhai-gpu-coredump %i`, and no `[Install]`. The `.rules` file matches `ACTION=="add"`, `SUBSYSTEM=="devcoredump"`, `KERNEL=="devcd[0-9]*"` and `ENV{SYSTEMD_WANTS}+="erhai-gpu-coredump@%k.service"`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_coredump.py -q`
Expected: FAIL (script and unit files don't exist).

- [ ] **Step 3: Implement `tablet/erhai-gpu-coredump`, the rule and the unit**

Order inside the script:
1. Validate the name.
2. Exit 0 if the devcd dir is gone.
3. Exit 0 if the `failing_device` basename isn't `$ERHAI_GPU_DEVICE`.
4. Create the store dir (0700).
5. Copy `data` to a `.tmp` in the store with `umask 077`; on failure, remove the `.tmp`, log, set rc=1.
6. On success, `mv` the `.tmp` to the final name, adding `-N` from 2 if the name exists.
7. Always write `1` to `data` when step 3 passed.
8. Rotate to `$ERHAI_COREDUMP_KEEP` files.

The rule and unit use exactly the strings asserted in Step 1.

- [ ] **Step 4: Run them to verify they pass**

Run: `python3 -m pytest tests/test_coredump.py -q`
Expected: 8 passed.

- [ ] **Step 5: Install wiring, with its test first**

In `tests/test_install_docs.py::InstallSh`, add `test_installs_coredump_chain`: install.sh contains `erhai-gpu-coredump`, `70-erhai-gpu-coredump.rules` installed to `/etc/udev/rules.d/`, `erhai-gpu-coredump@.service` in `UNIT_FILES`, `udevadm control --reload`, and `uninstall` removes the rule. Run it and see it FAIL. Then edit `tablet/install.sh`:
- install the script to `$LIB` (0755) and the rule to `/etc/udev/rules.d/` (0644);
- add the unit to `UNIT_FILES`;
- run `udevadm control --reload` after `systemctl daemon-reload` (the same on uninstall);
- don't enable the unit (udev starts it).

Run `python3 -m pytest tests -q`. Expected: all pass (282 + new).

- [ ] **Step 6: Commit (lab repo)**

```bash
git add tablet/erhai-gpu-coredump tablet/70-erhai-gpu-coredump.rules tablet/erhai-gpu-coredump@.service tablet/install.sh tests/test_coredump.py tests/test_install_docs.py
git commit -m "coredump: save and free every GPU devcoredump (udev-started copier)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: g1 checks the saved crash dump (T7)

**Files:**
- Modify: `tools/igt-recovery/igt-recovery` (`run()`, lines 52–78)
- Modify: `tests/test_g1.py`

**Interfaces:**
- Consumes: `$ERHAI_COREDUMP_DIR/*.bin` from Task 5 (default `/var/lib/erhai-gpu/coredumps`).
- Produces: in `run()`, for `gpu-fault` only, a new summary field `dump=<ok|missing|incomplete:<section>>` on the `igt-recovery: subtest=...` line. PASS also requires `dump=ok`. Env overrides for tests: `ERHAI_COREDUMP_DIR`, `ERHAI_DUMP_WAIT_S` (default 30), `ERHAI_DEBUGFS_GPU_GLOB` (default `/sys/kernel/debug/dri/*/gpu`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_g1.py`, add a class that runs the wrapper's dump-check function in isolation: extract it into a sourced shell function `dump_check <marker-file>`, callable as `igt-recovery dump-check <marker>`. Tests:
- `test_dump_check_ok`: a `.bin` newer than the marker containing `ringbuffer:`, `gmu-log:`, `gmu-hfi:`, `queue-history[`, plus a fake debugfs gpu file with the same lines → stdout `dump=ok`, rc 0.
- `test_dump_check_reports_missing_bin`: no new `.bin`, `ERHAI_DUMP_WAIT_S=1` → `dump=missing`, rc 1, within 3 s.
- `test_dump_check_reports_incomplete`: `.bin` without `gmu-hfi:` → `dump=incomplete:gmu-hfi`, rc 1.
- `test_old_bin_is_ignored`: a `.bin` older than the marker only → `dump=missing`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest tests/test_g1.py -q -k dump_check`
Expected: FAIL (no `dump-check` subcommand).

- [ ] **Step 3: Implement**

`run()` touches a marker before starting the IGT binary. For `gpu-fault`, after the journal capture it calls `dump_check` (poll once per second up to `$ERHAI_DUMP_WAIT_S` for `find $ERHAI_COREDUMP_DIR -name '*.bin' -newer $marker`; check the four headers in the newest one, and the same four in the first readable `$ERHAI_DEBUGFS_GPU_GLOB`). The pass condition gains `dump=ok`; the `FAIL g1 ...` hint lists `dump=ok`. `hangcheck` runs skip the dump check (`dump=n/a`). Add the `dump-check` case to the `case` dispatcher.

- [ ] **Step 4: Run them to verify they pass**

Run: `python3 -m pytest tests -q`
Expected: all pass.

- [ ] **Step 5: Commit (lab repo)**

`git commit -m "g1: require a saved GPU crash dump with all sections after gpu-fault" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`

---

### Task 7: Candidate 71-a8xx-crashstate, local build first (T5)

**Files:**
- Create: `candidates/71-a8xx-crashstate/extra.config`, `cmdline`, `BASE_SHA`, `STACK`, `0001-*.patch` … `0004-*.patch` (generated)
- Modify: `tests/test_assert_config.py`

**Interfaces:**
- Consumes: kernel branch `erhai-gpu-recovery-deadlock` (Tasks 1–4) in `~/Development/erhai-gpu-71-wt`.

- [ ] **Step 1: Failing config test**

In `tests/test_assert_config.py`, add `test_candidate_71_detects_hung_tasks`: `candidates/71-a8xx-crashstate/extra.config` contains `CONFIG_DETECT_HUNG_TASK=y` and `CONFIG_DEFAULT_HUNG_TASK_TIMEOUT=120`, plus the existing four lines from `70-pr`. Run `python3 -m pytest tests/test_assert_config.py -q`. Expected: FAIL (no such candidate).

- [ ] **Step 2: Create the candidate**

`mkdir candidates/71-a8xx-crashstate`. Write `extra.config` with exactly these lines:
```
CONFIG_SM_GPUCC_8750=m
CONFIG_FTRACE=y
CONFIG_TRACING=y
CONFIG_TRACEPOINTS=y
CONFIG_DETECT_HUNG_TASK=y
CONFIG_DEFAULT_HUNG_TASK_TIMEOUT=120
```
Copy `candidates/70-pr/cmdline`. Then:
```bash
tools/export-patches.sh ~/Development/erhai-gpu-71-wt erhai-gpu-recovery-deadlock 71-a8xx-crashstate --base dbf6edb5ef38d6540c689cc6b0de8ad7b5ddca2a
```
Expected: 4 patches, and `STACK` = the branch tip. Then `python3 -m pytest tests -q`. Expected: all pass, including the tracer and fragment-syntax invariants.

- [ ] **Step 3: Local build (before any CI)**

Run: `tools/build-local.sh 71-a8xx-crashstate --kernel-dir ~/Development/erhai-gpu-71-wt`
Expected: `build-local: 71-a8xx-crashstate built ...; assets in out/71-a8xx-crashstate/`, and `out/71-a8xx-crashstate/config-*` contains `CONFIG_DETECT_HUNG_TASK=y`.

- [ ] **Step 4: Commit (lab repo)**

`git add candidates/71-a8xx-crashstate tests/test_assert_config.py && git commit -m "candidates/71-a8xx-crashstate: recovery guard, async crash-state free, a8xx dumps" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`. Push the lab repo, and with it the GitHub CI, only after Step 3 passed.

---

### Task 8: Device validation (T8)

**Files:** none (runs on the tablet). Every step needs the user at the tablet; sudo commands are the user's.

- [ ] **Step 1: Install, queue g0, boot the candidate**

`sudo tablet/install.sh` (installs the copier chain), then `sudo erhai-gpu-lab fetch 71-a8xx-crashstate --from-dir out/71-a8xx-crashstate`, `sudo erhai-gpu-lab queue g0 --expect 71-a8xx-crashstate`, reboot and pick `…-lab-71-a8xx-crashstate` in rEFInd.
Expected: g0 has the same 2 config FAILs as 70-pr or fewer (`hung_task_timeout_secs` should now PASS).

- [ ] **Step 2: g1**

`sudo erhai-gpu-lab g1 --yes`
Expected:
- 6/6 PASS;
- every gpu-fault line has `dump=ok`;
- `/var/lib/erhai-gpu/coredumps/` gains 5 `.bin` files (0600);
- the journal has `erhai-lab: crashstate capture (...) took N us` lines (record the max N for the RFC TODO).

- [ ] **Step 3: Natural repro, 30 min**

Bluetooth on, HDB 630, music. Afterwards, check the journal: for every `hangcheck recover!`, `power/runtime_status` returned to `active` and the completed fence advanced within 10 s.
Expected:
- no forced reset;
- no `blocked for more than` (hung task) lines;
- no more than 3 recoveries in a row less than 5 s apart;
- at least one `.bin` per wedge burst.

- [ ] **Step 4: devcoredump disabled (last test of this boot)**

`echo 1 | sudo tee /sys/class/devcoredump/disabled`, then `sudo erhai-gpu-lab g1 --yes --runs 1 --hangcheck 0`.
Expected: `recover=1`, the GPU active again, no hang. The dump check reports `dump=missing`, so this g1 run records FAIL by design (dumps are disabled); judge it only on `recover=1` and the GPU returning to active. Reboot afterwards (the knob is write-once).

---

### Task 9: Upstream and erhai PR preparation (T9)

**Files:** none in the repos; drafts in `~/gpu-lab-evidence/upstream/`.

- [ ] **Step 1: Draft the erhai PR and the freedreno series**

The erhai PR to TheMojoMan carries the three upstream patches from Tasks 1–3 (not Task 4's LAB ONLY patch), with the Task 8 evidence. The freedreno series drafts are made with `git format-patch -3 --cover-letter` from the worktree. The cover letter states: "a6xx/a7xx: build + pure-move review only; Tested-by welcome", the A830 evidence, and a Link to the July 2025 review. No AI trace anywhere.

- [ ] **Step 2: Stop for the user**

Show both drafts and wait for explicit approval before any push, PR or mail (each is outward-facing).
