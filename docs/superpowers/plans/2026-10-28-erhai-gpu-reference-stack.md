# erhai GPU reference stack (candidate 60-gpu-reference) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the OnePlus Pad 3's Adreno 830 sleep and wake under runtime PM again by replacing the port's hand-written GPU device tree, catalog and GMU workarounds with the Qualcomm/yzddmr6 reference stack, built and measured as lab candidate `60-gpu-reference`.

**Architecture:** Two repositories. The kernel fork `~/Development/oneplus-erhai-linux` gets a branch `erhai-gpu-reference` off `origin/7.3-rc5` (`1dc134a720`) carrying seven ordered patches (provider nodes, gxclkctl re-bind, GPU/GMU nodes, A830 catalog, six reverts plus a hand-written gate removal, defconfig, one `dev_warn`). The new lab repo `~/Development/erhai-gpu-lab` (copy of `~/Development/charging-fixes`'s layout) exports that branch as patch files, builds a UKI in CI, installs it beside the package kernel, and carries the tools that make every ladder rung a pass/fail line.

**Tech Stack:** Linux 7.3-rc5 (arm64, DT, drm/msm, clk/qcom), bash, Python 3 stdlib `unittest`, C with EGL/GLES2 (Mesa), GitHub Actions (`ubuntu-24.04-arm`), `ukify`.

**Spec:** `/home/nadelacruz/.gstack/projects/TheMojoMan-oneplus-erhai-linux/nadelacruz-erhai-pps-dual-pump-design-20261027-171129.md` (lines 1-154 the design; `## Eng review` the decision ledger D1-D11 and tasks T1-T12). Also read `/home/nadelacruz/.gstack/projects/TheMojoMan-oneplus-erhai-linux/nadelacruz-erhai-pps-dual-pump-eng-review-test-plan-20261027-204030.md`.

## Global Constraints

- Nothing is implemented before the user's explicit go signal; this plan is executed task by task only after that.
- No AI trace in anything upstream-bound: kernel commit messages, the PR, the issue, `docs/ladder.md` excerpts quoted in them. No `Co-Authored-By`, no `Assisted-by`, no "Claude". Strip yzddmr6's `Co-Authored-By: Claude …` trailers when carrying their commits (design, Constraints; eng review R3-14 fix).
- Kernel commits: cherry-picks keep the original `Author:` (ROCKNIX, Akhil P Oommen, Jie Zhang) and add `Link: <source commit URL>` plus `Signed-off-by: <user>`; own commits use `erhai <area>: …` subjects or kernel prefixes (`drm/msm/a6xx:`), a body with real log lines, "Tested on a OnePlus Pad 3 (SM8750)", real 12-character `Fixes:` hashes where one applies (design, Constraints).
- `BASE_SHA` = `1dc134a720` (`origin/7.3-rc5` head on 2026-10-27). CI fetches TheMojoMan's repo at that sha and applies `candidates/60-gpu-reference/*.patch` with `patch -p1` (eng review A3).
- Candidate scope is fixed by the ledger: no GPU cooling map (D1); GMU node `gmu@3d37000` reg `0x68000` (D7); lab-only debug options never enter the PR (R3-17); `qcom_scm_gpu_init_regs(BIT(0) | BIT(3))` stays (R1-3 fix).
- `extra.config` must not disable the WCN stack; CI refuses a modules tarball without `wlan.ko` and `cnss2.ko` (F5).
- Lab tools are bash or stdlib Python 3, tested with `python3 -m unittest discover -s tests -v`; `tests.yml` also runs `bash -n` on every shell script.
- The tablet is the only test hardware; every kernel-side proof is a ladder rung (`docs/ladder.md`), never a claim.
- Branch commit order (so bisection prefixes can drop the reverts from the top, IFPC first): patches 1-4 (Task 3), then patch 6 defconfig (Task 5), then patch 7 `dev_warn` (Task 6), then patch 5's seven commits (Task 4). The design numbers the patches by purpose; the branch orders them for bisection. Full stack = 13 commits (14 with a speed-bin mapping).

## Review Focus

1. A boot on prefix `1+2` (providers + gxclkctl bound, port GPU nodes kept) must not Oops in `gdsc_register`; if the GX GDSC register still lies outside the window, the deferred-probe worker dies and Wi-Fi/audio vanish on that boot. Pinned by Task 11 step 4 (prefix build and `gpu-checks.sh g0` driver-bound line).
2. A speed-bin fuse value outside Jie Zhang's table makes the GPU refuse to probe; the desktop would come up on llvmpipe or not at all. Pinned by Task 10 step 2 (g-1 fuse read) and Task 3 step 10 (mapping commit when needed).
3. A suspend hang after `a6xx_rpmh_stop` is restored looks like a freeze; the DPM watchdog must name `3d00000.gpu`/`3d37000.gmu` and the checker must classify it as GMU-attributed. Pinned by Task 8 step 5 (clause-1 DPM line fixture).
4. A silent reset with IFPC on leaves no pstore record on this board; the checker must not read "no record" as "no evidence either way" without first confirming the evidence paths were armed. Pinned by Task 8 step 7 (evidence-path check) and Task 9 (PON reason).
5. `gnome-shell` falling back to llvmpipe after the catalog swap passes every kernel check and still ruins the device. Pinned by Task 8 step 4 (regression contract check 5 reads `/proc/<pid>/maps`).

---

### Task 1: Lab repo skeleton `erhai-gpu-lab`

**Files:**
- Create: `~/Development/erhai-gpu-lab/` as a git repo: `BASE_SHA`, `candidates/60-gpu-reference/cmdline`, `candidates/60-gpu-reference/extra.config` (placeholder, final content in Task 5), `ci/build-candidate.sh`, `ci/assert-config.sh`, `.github/workflows/kernel.yml`, `.github/workflows/tests.yml`, `.gitignore`, `LICENSE`, `README.md`, `TODOS.md`, `tablet/erhai-lab`, `tablet/install.sh`, `tests/labtool.py`, `tests/test_fetch.py`, `tests/test_assert_config.py`, `docs/ladder.md` (stub, filled in Task 10)
- Source to copy from: `~/Development/charging-fixes/` (same relative paths; never copy `candidates/43-*`, `archive/`, `docs/suspend-charging.md`, `docs/vendor-pps.md`)
- Test: `tests/test_fetch.py` (copied, must stay green after the `REPO` change)

**Interfaces:**
- Consumes: nothing.
- Produces: repo root `~/Development/erhai-gpu-lab` with `python3 -m unittest discover -s tests -v` green; `tablet/erhai-lab` with `REPO = "nadelacruz-00/erhai-gpu-lab"`; `candidates/BASE_SHA` containing `1dc134a720fdbb…` (full 40-char sha of `origin/7.3-rc5`); `candidates/60-gpu-reference/cmdline` containing exactly `root=PARTLABEL=linux rootwait rw rootfstype=ext4 fw_devlink=off console=tty0 loglevel=4 clk_ignore_unused pd_ignore_unused panic=30 usbcore.autosuspend=-1 log_buf_len=8M`.

- [ ] **Step 1: Copy the skeleton and initialise git**

Run from `~/Development`: `mkdir -p erhai-gpu-lab && cd erhai-gpu-lab && git init -b main` then copy, preserving modes, from `../charging-fixes`: `ci/`, `.github/`, `.gitignore`, `LICENSE`, `tablet/erhai-lab`, `tablet/install.sh`, `tests/labtool.py`, `tests/test_fetch.py`, `tests/test_assert_config.py`. Create empty `candidates/60-gpu-reference/` and `docs/`.

- [ ] **Step 2: Write the failing test for the repo constant**

Add to `tests/test_fetch.py` (class `Fetch`, or a new class `RepoIdentity`):

```python
def test_repo_is_the_gpu_lab(self):
    self.assertEqual(lab.REPO, "nadelacruz-00/erhai-gpu-lab")
```

- [ ] **Step 3: Run the tests to verify the new one fails**

Run: `python3 -m unittest tests.test_fetch -v`
Expected: `test_repo_is_the_gpu_lab` FAIL (`'nadelacruz-00/erhai-charging-lab' != 'nadelacruz-00/erhai-gpu-lab'`), all others PASS.

- [ ] **Step 4: Point the tool at the new repo**

Edit `tablet/erhai-lab` line 32: `REPO = "nadelacruz-00/erhai-gpu-lab"`. Edit the docstring at the top of the file: replace "charging test lab" wording with "GPU runtime-PM lab" and delete the sentence about charging-specific commands landing in "eng review task T4".

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: all PASS (16 fetch tests + 1 new + 7 assert-config).

- [ ] **Step 6: Write `BASE_SHA`, `cmdline`, placeholder `extra.config`**

`candidates/BASE_SHA`: the full sha from `git -C ~/Development/oneplus-erhai-linux rev-parse origin/7.3-rc5` (must start `1dc134a720`). `candidates/60-gpu-reference/cmdline`: the exact string from the Interfaces block (one line, trailing newline). `candidates/60-gpu-reference/extra.config`: the single line `CONFIG_SM_GPUCC_8750=y` for now.

- [ ] **Step 7: Write `README.md`, `TODOS.md`, `docs/ladder.md` stub**

`README.md`: title `# erhai-gpu-lab`, one paragraph (the freeze, the two DT windows, candidate 60), the "How it works" and "Tests" sections copied from charging's README with `43-pr-dual-pump` replaced by `60-gpu-reference`, and a "Credits" section naming yzddmr6 (`linux-sm8750-erhai`), Akhil P Oommen and Jie Zhang (Qualcomm A830 series), ROCKNIX (`bf8097a3fc`), with repository URLs. `TODOS.md`: the two entries verbatim from the design's `### TODOS.md (erhai-gpu-lab; …)` block (D10 `62-gpu-cooling-map`, D11 upstream the GX-attach warning). `docs/ladder.md`: heading `# Ladder` and the line `Filled in by the ladder task.`

- [ ] **Step 8: Verify the workflows parse and the scripts lint**

Run: `bash -n ci/build-candidate.sh && bash -n ci/assert-config.sh && sh -n tablet/install.sh && python3 -c "import yaml,sys; [yaml.safe_load(open(f)) for f in ['.github/workflows/kernel.yml','.github/workflows/tests.yml']]" 2>/dev/null || python3 -c "print('yaml module absent; skip')"`
Expected: no output other than the optional skip line, exit 0.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "lab: erhai-gpu-lab skeleton from erhai-charging-lab, candidate 60-gpu-reference"
```

---

### Task 2: `tools/export-patches.sh` with a drift check

**Files:**
- Create: `tools/export-patches.sh`
- Test: `tests/test_export_patches.py`

**Interfaces:**
- Consumes: `candidates/BASE_SHA` (Task 1).
- Produces: `tools/export-patches.sh <kernel-dir> <branch> <candidate>`: deletes `candidates/<candidate>/*.patch`, runs `git -C <kernel-dir> format-patch --zero-commit --no-signature --no-numbered -o candidates/<candidate>/ $(cat candidates/BASE_SHA)..<branch>`, writes the branch tip's full sha to `candidates/<candidate>/STACK`, prints one line per written file, exits non-zero if `<branch>` is not a descendant of `BASE_SHA` or if the kernel dir is not a git repo. `--prefix N` keeps only the first N commits above `BASE_SHA` (`<branch>~(count-N)`), for the bisection prefixes.

- [ ] **Step 1: Write the failing tests**

`tests/test_export_patches.py`, stdlib only, `from labtool import REPO_ROOT`; a helper `make_repo(tmp) -> (kernel_dir, base_sha)` that `git init`s a repo, makes one base commit, records its sha into a temporary `candidates/BASE_SHA` under a copy of the repo layout, then adds three commits `a`, `b`, `c` on branch `work`:

```python
def test_exports_one_file_per_commit_and_stack(self):
    out = run_export(kernel, "work", "cand")        # subprocess, returns CompletedProcess
    files = sorted(p.name for p in (cands / "cand").glob("*.patch"))
    self.assertEqual(len(files), 3)
    self.assertTrue(files[0].startswith("0001-"))
    self.assertEqual((cands / "cand" / "STACK").read_text().strip(), tip_sha("work"))

def test_removes_stale_patch_files(self):
    (cands / "cand" / "0009-stale.patch").write_text("stale")
    run_export(kernel, "work", "cand")
    self.assertFalse((cands / "cand" / "0009-stale.patch").exists())

def test_prefix_keeps_first_n_commits(self):
    run_export(kernel, "work", "cand", "--prefix", "2")
    self.assertEqual(len(list((cands / "cand").glob("*.patch"))), 2)

def test_branch_not_on_base_fails(self):
    r = run_export(kernel, "orphan", "cand")        # branch created with --orphan
    self.assertNotEqual(r.returncode, 0)
    self.assertIn("not a descendant", r.stderr)

def test_patches_carry_original_author(self):
    run_export(kernel, "work", "cand")
    text = (cands / "cand" / "0001-a.patch").read_text()
    self.assertIn("From: Fixture Author <fixture@example.invalid>", text)
```

The fixture commits are authored with `git -c user.name='Fixture Author' -c user.email=fixture@example.invalid commit`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_export_patches -v`
Expected: all five FAIL (script not found / non-zero exit).

- [ ] **Step 3: Implement `tools/export-patches.sh`**

Bash, `set -euo pipefail`; usage line as in Interfaces; `BASE=$(tr -d '[:space:]' < "$ROOT/candidates/BASE_SHA")`; descendant check with `git -C "$K" merge-base --is-ancestor "$BASE" "$BRANCH" || { echo "… is not a descendant of BASE_SHA $BASE" >&2; exit 2; }`; `--prefix N` computes `COUNT=$(git -C "$K" rev-list --count "$BASE".."$BRANCH")` and uses `"$BRANCH~$((COUNT-N))"` as the range end; writes `STACK` from `git -C "$K" rev-parse "$END"`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_export_patches -v`
Expected: 5 PASS.

- [ ] **Step 5: Add the lint line and commit**

Append `&& bash -n tools/export-patches.sh` to the `bash -n` run in `.github/workflows/tests.yml`.

```bash
git add tools/export-patches.sh tests/test_export_patches.py .github/workflows/tests.yml
git commit -m "tools: export-patches.sh regenerates a candidate from BASE_SHA..branch and records STACK"
```

---

### Task 3: Kernel branch `erhai-gpu-reference`, patches 1-4

Work in `~/Development/oneplus-erhai-linux`. Builds are checked with object targets, not a full kernel: first `make ARCH=arm64 erhai_defconfig` once, then `make ARCH=arm64 dtbs` and `make ARCH=arm64 drivers/clk/qcom/gxclkctl-kaanapali.o drivers/gpu/drm/msm/adreno/a6xx_catalog.o drivers/gpu/drm/msm/adreno/a8xx_gpu.o drivers/gpu/drm/msm/adreno/a6xx_gmu.o`.

**Files:**
- Modify: `arch/arm64/boot/dts/qcom/sm8750.dtsi` (`gx_clkctl` node :889-897, `gpucc` node :878-887, `gpu` node :687-831, `gmu` node :832-877), `arch/arm64/boot/dts/qcom/erhai.dts` (`&gmu_opp_table` override :2562-2580), `drivers/clk/qcom/gxclkctl-kaanapali.c` (:55-66), `drivers/gpu/drm/msm/adreno/a6xx_catalog.c` (:2158-2689 tables, :2829-2870 entry), `drivers/gpu/drm/msm/adreno/a8xx_gpu.c` (:224-232), `drivers/gpu/drm/msm/adreno/adreno_gpu.h` (helper near `adreno_is_x285`)
- Test: build targets above; `git log --format='%an%n%(trailers)'` checks

**Interfaces:**
- Consumes: reference remote `yzddmr6` = `https://github.com/yzddmr6/linux-sm8750-erhai.git`, branch `erhai/v0.3`, commits `bf8097a3fc` (ROCKNIX provider nodes), `2112ee5f83` (Akhil P Oommen GPU/GMU nodes), `696e6dd151` (Jie Zhang A830 catalog); mainline sm8750 GPU commits for `Link:` (find with `git log --oneline -S'gmu@3d6c000' -- arch/arm64/boot/dts/qcom/sm8750.dtsi` in a mainline checkout, or cite the lore series `20260809-pakala-gpu`).
- Produces: branch `erhai-gpu-reference` with four commits on top of `1dc134a720`, in this order: (1) providers, (2) `Revert "clk: qcom: gxclkctl-kaanapali — do not bind qcom,sm8750-gxclkctl"`, (3) GPU+GMU nodes, (4) catalog. Device names after boot: `3d64000.clock-controller`, `3d37000.gmu`.

- [ ] **Step 1: Create the branch and add the reference remote**

Run: `git fetch origin 7.3-rc5 && git checkout -b erhai-gpu-reference 1dc134a720 && git remote add yzddmr6 https://github.com/yzddmr6/linux-sm8750-erhai.git 2>/dev/null; git fetch yzddmr6 erhai/v0.3`
Expected: `git rev-parse HEAD` = `1dc134a720…`; `git cat-file -t bf8097a3fc` prints `commit`.

- [ ] **Step 2: Verify the pre-state (the failing condition)**

Run: `grep -n 'clock-controller@3d68000' arch/arm64/boot/dts/qcom/sm8750.dtsi; grep -c 'qcom,sm8750-gxclkctl' drivers/clk/qcom/gxclkctl-kaanapali.c`
Expected: one line at `:889`; count `1` (the comment only, no match-table entry).

- [ ] **Step 3: Patch 1, provider nodes (cherry-pick, keep author)**

Run: `git cherry-pick -x bf8097a3fc`. Resolve `sm8750.dtsi`: the port already has `gpucc` (:878) and `adreno_smmu` (:898) and a `gx_clkctl` at `@3d68000`; the result must contain exactly one of each: ROCKNIX's `gxclkctl: clock-controller@3d64000` block (reg `0x6000`, power-domains `rpmhpd RPMHPD_GFX`, `RPMHPD_GMXC`, `gpucc GPU_CC_CX_GDSC`), ROCKNIX's `gpucc` block (reg `0x9800`, power-domains `rpmhpd RPMHPD_MX`, `RPMHPD_CX`, `required-opps`), the SMMU block unchanged (identical in both trees). Delete the port's `gx_clkctl@3d68000` block. Keep the two `#include <dt-bindings/clock/qcom,…>` lines once. Fix the `gmu` node's `<&gx_clkctl GX_CLKCTL_GX_GDSC>` reference to `<&gxclkctl GX_CLKCTL_GX_GDSC>` (the label changes). Edit the commit message: keep ROCKNIX's text, strip any `Co-Authored-By`, add `Link: https://github.com/yzddmr6/linux-sm8750-erhai/commit/bf8097a3fc2f…` (full sha) and `Signed-off-by:` yours.

- [ ] **Step 4: Verify patch 1 builds**

Run: `make ARCH=arm64 erhai_defconfig >/dev/null && make ARCH=arm64 dtbs 2>&1 | tail -3 && fdtget arch/arm64/boot/dts/qcom/erhai.dtb /soc@0/clock-controller@3d64000 compatible`
Expected: dtbs build with no error; `fdtget` prints `qcom,sm8750-gxclkctl`; `fdtget … /soc@0/clock-controller@3d68000 compatible` fails (node gone).

- [ ] **Step 5: Patch 2, revert the un-bind**

Run: `git revert --no-edit 9c9eefdef1`, then `git commit --amend` to write the body: the Oops the original commit worked around (`gdsc_register` translation fault with the 4 KiB window at 0x3d68000), the new window (`0x3d64000`/`0x6000`, GDSC at `+0x4024` = `0x3d68024`), "Tested on a OnePlus Pad 3 (SM8750)" (filled in after g0), `Fixes: 9c9eefdef1xx ("clk: qcom: gxclkctl-kaanapali — do not bind qcom,sm8750-gxclkctl")` with the real 12-char hash.

- [ ] **Step 6: Verify patch 2**

Run: `grep -n '"qcom,sm8750-gxclkctl"' drivers/clk/qcom/gxclkctl-kaanapali.c && make ARCH=arm64 drivers/clk/qcom/gxclkctl-kaanapali.o 2>&1 | tail -1`
Expected: the match-table line is back; object builds.

- [ ] **Step 7: Patch 3, GPU + GMU nodes (cherry-pick, keep author)**

Run: `git cherry-pick -x 2112ee5f83`. Resolve `sm8750.dtsi` so the result has: the reference `gpu@3d00000` (reg `0x6d000` + `cx_mem` `0x2000`, no `cx_dbgc`), the reference `gpu_opp_table` (every OPP with `opp-supported-hw`, `opp-peak-kBps` as in the reference, `operating-points-v2-adreno`), `nvmem-cells = <&gpu_speed_bin>`, `qcom,gmu = <&gmu>`, the `zap-shader` node keeping the port's `firmware-name = "qcom/gen80000_zap.mbn"` (the reference's `memory-region` line may stay), the reference `gmu@3d37000` (`qcom,adreno-gmu-830.1`, reg `0x68000`, six clocks, `power-domains = <&gpucc GPU_CC_CX_GDSC>, <&gxclkctl GX_CLKCTL_GX_GDSC>`, `gmu_opp_table` with 500 MHz LOW_SVS and 650 MHz SVS), and the reference `qfprom@221c8000` with `gpu_speed_bin: gpu-speed-bin@138 { reg = <0x138 0x2>; bits = <0 9>; }`. Do NOT take the GPU cooling map (D1): leave the port's `cooling-maps` untouched. In `erhai.dts` delete the `&gmu_opp_table { /delete-node/ … }` override (:2562-2580) and keep `&gpu { status = "okay"; }`. Commit message: Akhil's text, strip `Assisted-by:`/`Co-Authored-By:`, add `Link:` to yzddmr6's commit and `Link:` to the mainline commit (or the lore series), one paragraph stating the three GMU windows (mainline 0x3d6c000/0x32000, yzddmr6 0x3d37000/0x68000 kept here, port 0x3d6a000/0x35000) and that the driver normalizes via `mmio_offset`, and your `Signed-off-by`.

- [ ] **Step 8: Verify patch 3**

Run: `make ARCH=arm64 dtbs 2>&1 | tail -1 && fdtget arch/arm64/boot/dts/qcom/erhai.dtb /soc@0/gpu@3d00000 reg && fdtget arch/arm64/boot/dts/qcom/erhai.dtb /soc@0/gmu@3d37000 compatible && fdtget -l arch/arm64/boot/dts/qcom/erhai.dtb /soc@0/gmu@3d37000/opp-table`
Expected: reg contains `0 64028672 0 446464` (0x3d00000, 0x6d000); compatible `qcom,adreno-gmu-830.1 qcom,adreno-gmu`; opp-table lists exactly `opp-500000000` and `opp-650000000`; `fdtget … /soc@0/gmu@3d6a000 compatible` fails.

- [ ] **Step 9: Patch 4, A830 catalog (cherry-pick, keep author)**

Run: `git cherry-pick -x 696e6dd151`. Resolve `a6xx_catalog.c`: delete the port's `gen8_0_0_nonctxt_regs`, `gen8_0_1_protect_regs`/`gen8_0_1_protect`, `gen8_0_1_dyn_pwrup_reglist*`, `gen8_0_1_pwrup_reglist*`, `gen8_0_1_ifpc_reglist*` blocks (:2158-2689) and the port's `0x44050001` entry (:2829-2870); keep Jie Zhang's `a830_nonctxt_regs`, `a830_protect` (`DECLARE_ADRENO_PROTECT(a830_protect, 64)`), `a830_pwrup_reglist`, `a830_ifpc_reglist`, `a830_dyn_pwrup_reglist` and his entry (`ADRENO_8XX_GEN1`, `gmu_chipid 0x8000100`, `preempt_record_size = 13536 * SZ_1K`, speedbins `{0,0} {252,0} {242,1} {232,2} {221,3} {190,4}`, no `.zapfw`); keep the `BUILD_BUG_ON(a830_protect…)` line. Resolve `a8xx_gpu.c:224-232`: keep TheMojoMan's braces, change the condition to `if ((adreno_is_x285(adreno_gpu) || adreno_is_a830(adreno_gpu)) && state)`. `adreno_gpu.h`: add `static inline int adreno_is_a830(struct adreno_gpu *gpu) { return gpu->info->chip_ids[0] == 0x44050001; }` next to `adreno_is_x285`. Commit message: Jie Zhang's text, `Link:` to yzddmr6's commit and to the lore series, `Signed-off-by` yours; keep the existing `Signed-off-by: Jie Zhang` and `Akhil P Oommen` lines.

- [ ] **Step 10: Verify patch 4 and the branch**

Run: `grep -c 'gen8_0_' drivers/gpu/drm/msm/adreno/a6xx_catalog.c; grep -n '0x44050001' drivers/gpu/drm/msm/adreno/a6xx_catalog.c drivers/gpu/drm/msm/adreno/adreno_gpu.h; make ARCH=arm64 drivers/gpu/drm/msm/adreno/a6xx_catalog.o drivers/gpu/drm/msm/adreno/a8xx_gpu.o 2>&1 | tail -1; git log --format='%h %an' 1dc134a720..HEAD; git log 1dc134a720..HEAD | grep -ciE 'co-authored-by|assisted-by|claude'`
Expected: `0` gen8_0 references; exactly one catalog entry line and the helper line; objects build; authors `ROCKNIX`, `<you>` (revert), `Akhil P Oommen`, `Jie Zhang`; trailer grep count `0`. If the g-1 fuse value (Task 10) is not one of `0, 252, 242, 232, 221, 190`, add a fifth commit here mapping it: one `{ <value>, <bin> }` row in the entry's `ADRENO_SPEEDBINS`, with the OPP mask argued in the body from the reference table.

---

### Task 4: Patch 5, retire the GMU workarounds

**Files:**
- Modify: `drivers/gpu/drm/msm/adreno/a6xx_gmu.c`, `drivers/gpu/drm/msm/adreno/a8xx_gpu.c`
- Test: build target `a6xx_gmu.o`, `a8xx_gpu.o`; greps below

**Interfaces:**
- Consumes: branch from Task 6 (patches 1-4, 6, 7 already committed).
- Produces: seven commits in this order (positions 7-13 of the stack): `Revert "erhai gpu: recover a PINNED GPU…"` (66500d1eef), `Revert "drm/msm/a6xx: erhai-7.3 b11: do not run the RSCC stop on A830…"` (e9faa3ec42), `Revert "drm/msm/a6xx: erhai: retry+escalate runtime GMU OOB timeouts…"` (cbfce58e8e, `a6xx_gmu.c` hunks only), `Revert "…retry the a8xx CM3 boot…"` (ef4d9b41ae), `erhai gpu: drop the GMU boot gate and the a8xx rpmh_off skip` (hand-written), `Revert "…always cold-boot the GMU on a8xx…"` (992da703ed), `Revert "…disable IFPC via erhai_no_ifpc param…"` (9c3aa45c45). Top of stack = IFPC revert, below it cold-boot, below it the gate removal: the bisection's drop order. After this task `grep -rn 'erhai_gmu_enable\|erhai_no_ifpc\|erhai_gmu_gpu' drivers/gpu/drm/msm` is empty and `git diff 1dc134a720..HEAD -- postinst` is empty.

- [ ] **Step 1: Verify the pre-state**

Run: `grep -c 'erhai_gmu_enable\|erhai_no_ifpc' drivers/gpu/drm/msm/adreno/a6xx_gmu.c`
Expected: a positive count (≥ 10).

- [ ] **Step 2: First four reverts, newest first**

Run in this order, resolving conflicts toward "the pre-commit text" each time: `git revert --no-edit 66500d1eef`; `git revert --no-edit e9faa3ec42`; `git revert -n cbfce58e8e && git checkout HEAD -- postinst && git commit` (body: "postinst left untouched: the original commit also renamed UKIs"); `git revert --no-edit ef4d9b41ae`. Each revert body gets one sentence naming the DT bug that motivated the original (`9c9eefdef1` window / RSCC at `gpu+0x50000` outside the 0x40000 window) and "Tested on a OnePlus Pad 3 (SM8750)" (filled in after g0).

- [ ] **Step 3: Hand-written removal of the gate and the rpmh_off skip**

In `a6xx_gmu.c`: delete the `erhai_gmu_enable` block (`bool erhai_gmu_enable;`, `static struct a6xx_gpu *erhai_gmu_gpu;`, `erhai_gmu_enable_set()`, `erhai_gmu_enable_ops`, `module_param_cb(erhai_gmu_enable, …)`, both `MODULE_PARM_DESC` lines that remain, the comment block above them, :19-98 at BASE); delete `if (!erhai_gmu_enable) { return -ENODEV; }` and its comment in `a6xx_gmu_resume` (:1500-1506 at BASE); delete `erhai_gmu_gpu = a6xx_gpu;` in `a6xx_gmu_init` (:2588 at BASE); delete the `if (adreno_is_a8xx(adreno_gpu)) { return; }` early return and its comment in `a6xx_gmu_rpmh_off` (:1168-1186 at BASE). Leave `qcom_scm_gpu_init_regs(BIT(0) | BIT(3))` and its comment. Commit as `erhai gpu: drop the GMU boot gate and the a8xx rpmh_off skip` with a body quoting the boot line it removes (`adreno_load_gpu *ERROR* Couldn't power up the GPU: -19`) and why the skip is no longer needed (RSCC now inside the mapped window).

- [ ] **Step 4: Last two reverts**

Run: `git revert --no-edit 992da703ed`; `git revert --no-edit 9c3aa45c45` (this one also removes `MODULE_PARM_DESC(erhai_no_ifpc)`; if the gate-removal commit already deleted that line, resolve by leaving it deleted). Same body sentences as step 2.

- [ ] **Step 5: Verify the pre-state is gone and it builds**

Run: `grep -rn 'erhai_gmu_enable\|erhai_no_ifpc\|erhai_gmu_gpu' drivers/gpu/drm/msm; git diff 1dc134a720..HEAD --stat -- postinst; git rev-list --count 1dc134a720..HEAD; make ARCH=arm64 drivers/gpu/drm/msm/adreno/a6xx_gmu.o drivers/gpu/drm/msm/adreno/a8xx_gpu.o 2>&1 | grep -ciE 'error|warning: unused'`
Expected: empty grep; empty postinst diff; `13` (or `14` with the speed-bin mapping); `0`.

---

### Task 5: Patch 6, defconfig and the lab-only `extra.config`

**Files:**
- Modify: `~/Development/oneplus-erhai-linux/arch/arm64/configs/erhai_defconfig:830`
- Modify: `~/Development/erhai-gpu-lab/candidates/60-gpu-reference/extra.config`
- Test: `~/Development/erhai-gpu-lab/tests/test_assert_config.py`

**Interfaces:**
- Consumes: Task 1 repo, Task 3 branch (this commit is position 5 of the stack, before patch 7 and the reverts).
- Produces: kernel commit `erhai config: build the SM8750 GPU clock controller in` (`CONFIG_SM_GPUCC_8750=y`, `Link:` to yzddmr6 `bd4f02e3f7`); `extra.config` with exactly: `CONFIG_SM_GPUCC_8750=y`, `CONFIG_EXPERT=y`, `# CONFIG_RESET_SIMPLE is not set`, `CONFIG_PM_DEBUG=y`, `CONFIG_DPM_WATCHDOG=y`, `CONFIG_DPM_WATCHDOG_TIMEOUT=60`, `CONFIG_DPM_WATCHDOG_WARNING_TIMEOUT=30`, `CONFIG_SOFTLOCKUP_DETECTOR=y`, `CONFIG_DETECT_HUNG_TASK=y`, `# CONFIG_HARDLOCKUP_DETECTOR is not set`.

- [ ] **Step 1: Write the failing test rows**

Add to `tests/test_assert_config.py`:

```python
def test_candidate_60_fragment_is_asserted_verbatim(self):
    frag = (CANDIDATES / "60-gpu-reference" / "extra.config").read_text()
    self.assertIn("CONFIG_DPM_WATCHDOG_TIMEOUT=60\n", frag)
    self.assertIn("# CONFIG_RESET_SIMPLE is not set\n", frag)
    r = run(frag, frag)                       # a .config that matches the fragment exactly
    self.assertEqual(r.returncode, 0, r.stderr)

def test_dropped_dpm_watchdog_fails(self):
    frag = (CANDIDATES / "60-gpu-reference" / "extra.config").read_text()
    r = run(frag, frag.replace("CONFIG_DPM_WATCHDOG=y\n", "# CONFIG_DPM_WATCHDOG is not set\n"))
    self.assertNotEqual(r.returncode, 0)
    self.assertIn("DPM_WATCHDOG", r.stderr)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_assert_config -v`
Expected: the two new tests FAIL (fragment lacks the lines).

- [ ] **Step 3: Write `extra.config` and the defconfig commit**

Write the ten lines from Interfaces into `candidates/60-gpu-reference/extra.config`. In the kernel tree, change `erhai_defconfig:830` to `CONFIG_SM_GPUCC_8750=y` and commit with the subject above; body: yzddmr6's reason ("a =m gpucc strands the whole GPU chain" when the initramfs has no module loader), `Link:` to `bd4f02e3f7`.

- [ ] **Step 4: Run the tests and the real merge**

Run: `python3 -m unittest tests.test_assert_config -v` then in the kernel tree `make ARCH=arm64 erhai_defconfig >/dev/null && scripts/kconfig/merge_config.sh -m .config ~/Development/erhai-gpu-lab/candidates/60-gpu-reference/extra.config >/dev/null && make ARCH=arm64 olddefconfig >/dev/null && bash ~/Development/erhai-gpu-lab/ci/assert-config.sh ~/Development/erhai-gpu-lab/candidates/60-gpu-reference/extra.config .config && grep -E '^CONFIG_(CNSS2|QCA_CLD_WLAN|SM_GPUCC_8750)' .config`
Expected: tests PASS; `assert-config.sh` exits 0; the WCN symbols are still `=y`/`=m` as in the base defconfig and `CONFIG_SM_GPUCC_8750=y`.

- [ ] **Step 5: Commit the lab side**

```bash
git add candidates/60-gpu-reference/extra.config tests/test_assert_config.py
git commit -m "candidate 60: lab-only debug detectors in extra.config, asserted"
```

---

### Task 6: Patch 7, warn when the a8xx GX power domain is missing

**Files:**
- Modify: `drivers/gpu/drm/msm/adreno/a6xx_gmu.c` (after `gmu->gxpd = dev_pm_domain_attach_by_name(gmu->dev, "gx");` in `a6xx_gmu_init`)
- Test: build target; a dmesg assertion in Task 8's checker

**Interfaces:**
- Consumes: Task 5 branch (this commit is position 6 of the stack; Task 4's reverts come after it).
- Produces: commit `drm/msm/a6xx: warn when the GX power domain is unavailable on a8xx`; the exact message `GX power domain not available (%pe): hang recovery cannot collapse GX` printed with `dev_warn(gmu->dev, …)` only when `adreno_is_a8xx(adreno_gpu) && IS_ERR(gmu->gxpd)`; no behavior change.

- [ ] **Step 1: Verify the pre-state**

Run: `grep -n -A2 'attach_by_name(gmu->dev, "gx")' drivers/gpu/drm/msm/adreno/a6xx_gmu.c | tail -3`
Expected: the attach line followed by a blank line and the pwrlevels comment, no check.

- [ ] **Step 2: Add the warning**

Insert after the attach line: `if (adreno_is_a8xx(adreno_gpu) && IS_ERR(gmu->gxpd)) dev_warn(gmu->dev, "GX power domain not available (%pe): hang recovery cannot collapse GX\n", gmu->gxpd);` (kernel style, braces per checkpatch). Body: the erhai incident in two sentences (attach failed silently since 2026-08-25; every `gxpd` user is guarded by `IS_ERR_OR_NULL`, so the only symptom was an infinite `hangcheck recover!` loop with `cx gdsc didn't collapse`), "Tested on a OnePlus Pad 3 (SM8750)".

- [ ] **Step 3: Verify**

Run: `make ARCH=arm64 drivers/gpu/drm/msm/adreno/a6xx_gmu.o 2>&1 | grep -ci error; scripts/checkpatch.pl --no-signoff -g HEAD | tail -2`
Expected: `0`; checkpatch "has no obvious style problems" (or only the `Signed-off-by` note).

---

### Task 7: `tablet/setup.sh` and the `tools/gpu-hang` inducer

**Files:**
- Create: `tablet/setup.sh`, `tools/gpu-hang/gpu-hang.c`, `tools/gpu-hang/Makefile`
- Test: `tests/test_setup_sh.py` (static), on-tablet smoke `gpu-hang --iterations 1`

**Interfaces:**
- Consumes: nothing in-repo.
- Produces: `tablet/setup.sh` (idempotent `apt-get install -y` of exactly `trace-cmd mesa-utils vulkan-tools devmem2 libegl-dev libgles-dev`, prints `already installed` per package on a second run); `tools/gpu-hang/gpu-hang [--iterations N]` (default `0xFFFFFFFF`): EGL surfaceless context (`EGL_PLATFORM=surfaceless`, `EGL_EXT_platform_device` or `EGL_DEFAULT_DISPLAY`), GLES2, a 64×64 FBO, a fragment shader whose loop bound is a `uniform uint u_iters`, one draw, `glFinish()`; exit `0` when `glGetGraphicsResetStatusKHR()` (if `GL_KHR_robustness`) is `GL_NO_ERROR` and the draw completed, exit `3` on a detected reset, exit `4` if `glFinish` has not returned after 20 s (watchdog thread); prints one line `gpu-hang: iterations=<N> result=<completed|reset|timeout> elapsed=<s>`.

- [ ] **Step 1: Write the failing static test**

`tests/test_setup_sh.py`:

```python
def test_setup_installs_exactly_the_six_packages(self):
    text = (REPO_ROOT / "tablet" / "setup.sh").read_text()
    for p in ["trace-cmd", "mesa-utils", "vulkan-tools", "devmem2", "libegl-dev", "libgles-dev"]:
        self.assertIn(p, text)
    self.assertIn("dpkg -s", text)          # the idempotence check

def test_gpu_hang_builds(self):
    r = subprocess.run(["make", "-C", str(REPO_ROOT / "tools" / "gpu-hang"), "-n"], capture_output=True, text=True)
    self.assertEqual(r.returncode, 0, r.stderr)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_setup_sh -v`
Expected: both FAIL (files missing).

- [ ] **Step 3: Write `tablet/setup.sh`**

Bash: for each package, `dpkg -s "$p" >/dev/null 2>&1 && echo "$p already installed" || missing+=("$p")`; `sudo apt-get install -y "${missing[@]}"` only when non-empty.

- [ ] **Step 4: Write `tools/gpu-hang/gpu-hang.c` and `Makefile`**

`Makefile`: `gpu-hang: gpu-hang.c` with `$(CC) -O2 -Wall -o $@ $< -lEGL -lGLESv2 -lpthread`. The C file implements the Interfaces contract; the shader loop must not be elidable: accumulate into a value written to the fragment colour, bound from the uniform.

- [ ] **Step 5: Run the tests, build on the tablet, smoke**

Run: `python3 -m unittest tests.test_setup_sh -v && bash tablet/setup.sh && make -C tools/gpu-hang && ./tools/gpu-hang/gpu-hang --iterations 1`
Expected: tests PASS; packages installed; `gpu-hang: iterations=1 result=completed elapsed=…` exit 0. Do NOT run the default iterations yet (that is rung g1 control, Task 11).

- [ ] **Step 6: Commit**

```bash
git add tablet/setup.sh tools/gpu-hang/gpu-hang.c tools/gpu-hang/Makefile tests/test_setup_sh.py
git commit -m "tablet: setup.sh installs the ladder tools; tools/gpu-hang is the CP-hang inducer"
```

---

### Task 8: `tablet/gpu-checks.sh g0|cycles` with fixtures

**Files:**
- Create: `tablet/gpu-checks.sh`, `tests/test_gpu_checks.py`, `tests/fixtures/gpu-checks/{pass,fail-*}/…` (fake sysfs/dmesg trees)
- Test: `tests/test_gpu_checks.py`

**Interfaces:**
- Consumes: Task 7 tools; Task 9's result (`PON_REASON_PATH`, may be empty).
- Produces: `tablet/gpu-checks.sh g0` prints one line per check, format `PASS|FAIL|INFO <check-id> <observed value>`, exits `1` if any FAIL; env overrides for tests: `SYSROOT` (default `/`), `DMESG_CMD` (default `journalctl -k -b -q --no-pager`), `MAPS_PID` (default `pidof gnome-shell`), `PIN_STATE` (default `/run/erhai-gpu-pin-once.state`), `PON_REASON_PATH` (default empty → `INFO pon-reason not-readable`). Check ids and PASS conditions: `gxclkctl-bound` (`$SYSROOT/sys/devices/platform/soc@0/3d64000.clock-controller/driver` → `gxclkctl-kaanapali`); `gmu-genpd` (both `genpd:0:3d37000.gmu` and `genpd:1:3d37000.gmu` under `$SYSROOT/sys/devices`); `gx-gdsc-summary` (`sudo cat $SYSROOT/sys/kernel/debug/pm_genpd/pm_genpd_summary` contains `gx_clkctl_gx_gdsc`); `no-oops` (dmesg has no `Oops`/`Call trace`); `no-minus19` (dmesg has no `Couldn't power up the GPU`); `no-gx-warn` (dmesg has no `GX power domain not available`); `renderer` (`eglinfo -B` contains `FD830`); `zap` (dmesg has no `pas_init_image` error, has `zap`-related success or no zap error); `fuse` (`INFO` with the `speed_bin` value read from `$SYSROOT/sys/bus/nvmem/devices/qfprom*/nvmem` offset 0x138 when present); `pstore` (`$SYSROOT/sys/fs/pstore` exists and dmesg has `Registered ramoops`); `hung-task` (`$SYSROOT/proc/sys/kernel/hung_task_timeout_secs` exists); `dpm-watchdog` (`/proc/config.gz` has `CONFIG_DPM_WATCHDOG=y`); `pon-reason` (`INFO` value or `not-readable`); regression contract: `probe` (`$SYSROOT/sys/class/drm/renderD128/device/driver` → `msm`), `pin-released` (`PIN_STATE` contains `RELEASED`, polled up to `SETTLE+TIMEOUT` from `/etc/erhai/gpu-pin.conf`), `shell-on-gpu` (`/proc/$MAPS_PID/maps` contains `freedreno` or `libgallium` and not `llvmpipe`/`swrast`); intentional: `runtime-suspends` (`$SYSROOT/sys/devices/platform/soc@0/3d00000.gpu/power/runtime_status` reads `suspended` at least once in 60 s). `tablet/gpu-checks.sh cycles <seconds>` runs `trace-cmd record -b 4096 -e rpm:rpm_suspend -e rpm:rpm_resume -f 'name == "3d00000.gpu"' sleep <seconds>` and prints `cycles=<n> suspend=<n> resume=<n>`; with `TRACE_REPORT=<file>` it parses that file instead of recording.

- [ ] **Step 1: Write the failing tests**

`tests/test_gpu_checks.py` builds fixture trees under `tempfile` from `tests/fixtures/gpu-checks/` and runs the script with the env overrides:

```python
def test_pass_fixture_all_pass(self):
    r = run_checks("pass")
    self.assertEqual(r.returncode, 0, r.stdout)
    self.assertNotIn("FAIL", r.stdout)
    for cid in ["gxclkctl-bound", "gmu-genpd", "no-minus19", "no-gx-warn", "renderer", "probe", "pin-released", "shell-on-gpu", "runtime-suspends"]:
        self.assertRegex(r.stdout, rf"^PASS {cid} ", msg=cid)

def test_each_fail_fixture_fails_its_check(self):
    for cid in ["gxclkctl-bound", "gmu-genpd", "no-oops", "no-minus19", "no-gx-warn", "renderer", "zap", "pstore", "probe", "pin-released", "shell-on-gpu", "runtime-suspends"]:
        r = run_checks(f"fail-{cid}")
        self.assertEqual(r.returncode, 1, cid)
        self.assertRegex(r.stdout, rf"^FAIL {cid} ", msg=cid)

def test_control_row_on_package_kernel_shape(self):
    r = run_checks("control")          # -19 present, genpd:1 absent, contract 1-5 pass
    self.assertRegex(r.stdout, r"^FAIL no-minus19 ")
    self.assertRegex(r.stdout, r"^FAIL gmu-genpd ")
    for cid in ["probe", "zap", "renderer", "pin-released", "shell-on-gpu"]:
        self.assertRegex(r.stdout, rf"^PASS {cid} ")

def test_pon_reason_absent_is_info_not_fail(self):
    r = run_checks("pass", env={"PON_REASON_PATH": ""})
    self.assertRegex(r.stdout, r"^INFO pon-reason not-readable")

def test_dpm_watchdog_naming_gpu_is_reported(self):
    r = run_checks("fail-dpm-gpu")     # dmesg fixture with 'dpm_run_callback ... 3d00000.gpu'
    self.assertRegex(r.stdout, r"^FAIL suspend-hang-gpu ")

def test_cycles_parses_trace_report(self):
    r = run_cycles(fixture_report)     # TRACE_REPORT with 7 suspend + 7 resume lines for 3d00000.gpu and 3 for another device
    self.assertIn("cycles=7 suspend=7 resume=7", r.stdout)
```

(`suspend-hang-gpu` is one more check: FAIL when dmesg has a DPM-watchdog/`dpm_run_callback` line naming `3d00000.gpu`, `3d37000.gmu` or `gxclkctl`; absent → PASS.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_gpu_checks -v`
Expected: all FAIL (script missing).

- [ ] **Step 3: Write the fixtures**

One directory per fixture name with the minimal fake tree the check reads (`sys/devices/platform/soc@0/3d64000.clock-controller/driver` as a symlink, `sys/devices/genpd:0:3d37000.gmu/`, `dmesg.txt`, `maps.txt`, `pin.state`, `eglinfo.txt`, `pm_genpd_summary.txt`, `runtime_status`, `config.gz`); the `fail-<cid>` fixtures are `pass` with the one change that trips `<cid>`.

- [ ] **Step 4: Implement `tablet/gpu-checks.sh`**

Bash, one function per check returning the status word and value, a `report` helper that prints the line and sets a `failed` flag; commands that need the real machine (`eglinfo`, `sudo cat`, `trace-cmd`, `pidof`) are read from files when the matching env override points at a file (`EGLINFO_FILE`, `GENPD_SUMMARY_FILE`, `TRACE_REPORT`), so the fixtures drive them; `cycles` parses `trace-cmd report` lines by counting `rpm_suspend:` and `rpm_resume:` for `name=3d00000.gpu` only.

- [ ] **Step 5: Run the tests to verify they pass; lint**

Run: `python3 -m unittest tests.test_gpu_checks -v && bash -n tablet/gpu-checks.sh`
Expected: all PASS.

- [ ] **Step 6: Control row on the package kernel (the checker's own proof)**

On the tablet, booted on the package kernel: `sudo -v && tablet/gpu-checks.sh g0 | tee /tmp/g0-control.txt`
Expected: `FAIL no-minus19`, `FAIL gmu-genpd`, `FAIL gxclkctl-bound`, `PASS probe`, `PASS zap`, `PASS renderer FD830`, `PASS pin-released`, `PASS shell-on-gpu`, exit 1. Paste the output into `docs/ladder.md` as the g0 control row (Task 10).

- [ ] **Step 7: Commit**

```bash
git add tablet/gpu-checks.sh tests/test_gpu_checks.py tests/fixtures/gpu-checks
git commit -m "tablet: gpu-checks.sh g0 and cycles with pass/fail fixtures"
```

---

### Task 9: Bounded probe for a PMIC power-on-reason source (≤ 1 h)

**Files:**
- Modify: `docs/ladder.md` (result paragraph), `tablet/gpu-checks.sh` (set the default `PON_REASON_PATH` if found)
- Test: existing `tests/test_gpu_checks.py` stays green

**Interfaces:**
- Consumes: Task 8 checker.
- Produces: either a documented path (`PON_REASON_PATH=<sysfs path>` with the byte/field meaning and two observed values: after `sudo reboot` and after a power-key reset) or the sentence `PON reason: not readable from Linux on the current kernel; tried: <list>` in `docs/ladder.md`.

- [ ] **Step 1: Try the candidate sources, in this order, stop at the first readable one**

(a) `sudo hexdump -C /sys/bus/nvmem/devices/spmi_sdam0/nvmem | head` and compare against yzddmr6's reboot-mode cells (`efe984cb9f`, `31a79407cf` in the reference tree: `git -C <ref> show 31a79407cf`); (b) `ls /sys/bus/platform/devices | grep -i pon`, `/sys/class/power_supply/*/`, `dmesg | grep -i 'pon\|power-on'`; (c) the PMIC PON registers through the SPMI debugfs if `CONFIG_SPMI` debugfs exists (`/sys/kernel/debug/spmi/`). Record each attempt in one line.

- [ ] **Step 2: If found, prove it changes**

`sudo reboot`, read the value; then a power-key hold, read the value. Both values go into `docs/ladder.md`; set the checker default `PON_REASON_PATH` and extend the `pass` fixture with a `pon-reason` file so `INFO pon-reason <value>` appears.

- [ ] **Step 3: Verify and commit**

Run: `python3 -m unittest tests.test_gpu_checks -v`
Expected: PASS.

```bash
git add docs/ladder.md tablet/gpu-checks.sh tests/fixtures/gpu-checks
git commit -m "ladder: PMIC power-on-reason probe result"
```

---

### Task 10: `docs/ladder.md` and the g-1 fuse read

**Files:**
- Modify: `docs/ladder.md`
- Test: none (documentation); `tests.yml` lint unaffected

**Interfaces:**
- Consumes: design doc ladder table and attribution rule; Task 8 control output; Task 9 result.
- Produces: `docs/ladder.md` with sections `## Baseline` (the census table from the design with journal start times and boot IDs; the unattributed baseline `2 in 16 boots`), `## Attribution rule` (clauses 1-3 verbatim from the design, including the warm-reset-only pstore limit and the clause-3 A/B protocol), `## Rungs` (the g-1..g4 + PR table from the design with the eng-review changes: D4 inducer, D9 contract, D3 PON reason, idle-power method), `## Bisection` (prefix order `1+2`, `1-4`, `1-5` with `export-patches.sh --prefix`), `## Results` (empty rows to fill), and the g-1 row filled.

- [ ] **Step 1: Write the ladder**

Transcribe the sections above from the design (`/home/nadelacruz/.gstack/projects/TheMojoMan-oneplus-erhai-linux/nadelacruz-erhai-pps-dual-pump-design-20261027-171129.md`, Problem Statement census, Ladder, Bisection) applying the ledger: no IGT, `tools/gpu-hang`, `gpu-checks.sh g0` as the g0 instrument, the D9 contract rows, the D3 PON-reason line, no cooling map.

- [ ] **Step 2: g-1, read the fuse on the current kernel**

Run: `sudo devmem2 0x221c8138 h`
Expected: a 16-bit value; `speed_bin = value & 0x1ff` (bits 0-9 per the qfprom cell). Record the raw and masked values in the g-1 row. If the masked value is not in `0, 252, 242, 232, 221, 190`, note it and go back to Task 3 step 10 for the mapping commit.

- [ ] **Step 3: Record the control row and the idle-power baseline**

Paste Task 8 step 6's control output into `## Results › g0 control`. Measure the idle-power baseline on the package kernel: screen on, fixed brightness, Wi-Fi on, no apps, 30 min; `energy_now` (or `charge_now × voltage_now`) from `/sys/class/power_supply/erhai-adsp-bat/` at start and end → mW; record in the g4 row.

- [ ] **Step 4: Commit**

```bash
git add docs/ladder.md
git commit -m "ladder: baseline, attribution rule, rungs g-1..g4, g0 control row"
```

---

### Task 11: Export, CI build, fetch, g0 and g1 (operator rung)

**Files:**
- Modify: `candidates/60-gpu-reference/*.patch` (generated), `candidates/60-gpu-reference/STACK`, `docs/ladder.md` results

**Interfaces:**
- Consumes: Task 2 exporter, Task 3-6 branch, Task 7-8 tools, Task 10 ladder.
- Produces: GitHub Release `lab-60-gpu-reference-<run>`; ladder rows g0, g1 control, g1 filled with pasted `gpu-checks.sh` output and dmesg excerpts.

- [ ] **Step 1: Export and push**

Run: `tools/export-patches.sh ~/Development/oneplus-erhai-linux erhai-gpu-reference 60-gpu-reference && git add candidates && git commit -m "candidate 60: patch stack $(cut -c1-12 candidates/60-gpu-reference/STACK)" && gh repo create nadelacruz-00/erhai-gpu-lab --public --source . --push`
Expected: 13 patch files (4 + 7 + 1 + 1) or 14 with the speed-bin mapping; the `kernel` workflow starts.

- [ ] **Step 2: Fetch and boot**

Run on the tablet after the Release exists: `sudo tablet/erhai-lab fetch 60-gpu-reference`, reboot into it from rEFInd, `tablet/erhai-lab whoami`
Expected: `60-gpu-reference`.

- [ ] **Step 3: g0**

Run: `tablet/gpu-checks.sh g0 | tee /tmp/g0.txt`
Expected: every line `PASS` or `INFO`, exit 0. Paste into the ladder.

- [ ] **Step 4: If g0 fails, bisect by prefix**

`tools/export-patches.sh … --prefix 2` (providers + revert) → commit, CI, fetch, g0: expects `PASS gxclkctl-bound`, `PASS gmu-genpd` with the port's GPU nodes still present (`FAIL no-minus19` is expected on this prefix); then `--prefix 6` (patches 1-4 + defconfig + warn, workarounds still present: the GPU must boot and `no-gx-warn` must PASS); then from the full stack drop the top one at a time: `--prefix 12` (no IFPC revert), `--prefix 11` (no cold-boot revert), `--prefix 10` (no gate removal). Record each prefix's g0 in the ladder; stop at the first failing prefix and fix that patch.

- [ ] **Step 5: g1 control on the current kernel, then g1 on the candidate**

Boot the package or `lab-43` kernel, `echo auto | sudo tee /sys/devices/platform/soc@0/3d00000.gpu/power/control`, run `tools/gpu-hang/gpu-hang`; record exit code and `journalctl -k -b -q | grep -E 'hangcheck|recover|gdsc' | tail -20`. Then on the candidate, five runs with `control=auto` and one with `MODE=always` active: each must show exactly one `hangcheck recover!`, no `cx gdsc didn't collapse`, `gpu-hang` exit `3` (reset detected), gnome-shell still alive (`gpu-checks.sh g0` passes again afterwards).

- [ ] **Step 6: Commit the results**

```bash
git add docs/ladder.md
git commit -m "ladder: g0 and g1 results for 60-gpu-reference"
```

---

### Task 12: g2, g3 (if wedges), g4, issue and PR (operator rung)

**Files:**
- Modify: `docs/ladder.md`; kernel commit bodies ("Tested on a OnePlus Pad 3 (SM8750) …" lines, via `git rebase -i` is not available: use `git commit --amend` per commit with `git rebase --exec` scripted, or re-export)

**Interfaces:**
- Consumes: Task 11 results.
- Produces: ladder rows g2/g3/g4; a GitHub issue on `TheMojoMan/oneplus-erhai-linux`; a PR from `nadelacruz-00/oneplus-erhai-linux:erhai-gpu-reference` to `TheMojoMan/oneplus-erhai-linux:7.3-rc5` containing kernel patches 1-7 only.

- [ ] **Step 1: g2 soak**

8 h normal use with `control=auto`; `sudo tablet/gpu-checks.sh cycles 28800` in a tmux session; after: `cycles=<n>` ≥ 1000; dmesg scanned with the attribution rule; every GMU-attributed wedge must show the P1a sequence (`GMU OOB`/`HFI` timeout → one `hangcheck recover!` → no `cx gdsc didn't collapse` → `hw_init` ok). Any unattributed reset follows clause 3 (evidence paths, PON reason, A/B candidate `60-gpu-reference-ifpc-off` = `--prefix 12` with the IFPC revert re-applied).

- [ ] **Step 2: g3 only if g2 wedged**

`echo 967000000 | sudo tee /sys/class/devfreq/3d00000.gpu/max_freq`, repeat 8 h; then `900000000`; compare wedge counts; relate to the g-1 bin.

- [ ] **Step 3: g4**

48 h daily use; idle-power 30 min measurement as in Task 10 step 3 on the candidate with `control=auto`; pass = ≤ baseline; `vkcube` once, outcome noted (out of scope).

- [ ] **Step 4: Issue, then PR**

Open the issue first (title: `Adreno 830: GX power domain never attached and RSCC outside the GPU window; reference GPU stack candidate`), body: the two window findings with file:line, the live log excerpt from `~/gpu-hang-20261027-1554.log`, g0/g1 numbers, the three GMU windows, the no-wedge wording if g2+g4 saw none, the credits, the statement that no `Assisted-by` trailer is used. Fill the "Tested on a OnePlus Pad 3 (SM8750): …" lines in the seven kernel commit bodies with the ladder numbers (`git rebase --exec` with a sed script, then re-run `tools/export-patches.sh` and verify `git log 1dc134a720..HEAD | grep -ciE 'co-authored-by|assisted-by|claude'` = `0`). Push the fork branch; open the PR with `gh pr create --repo TheMojoMan/oneplus-erhai-linux --base 7.3-rc5` and a body that links the issue, the ladder, and the four credited sources.

- [ ] **Step 5: Commit the final ladder**

```bash
git add docs/ladder.md
git commit -m "ladder: g2-g4 results; issue and PR links"
```
