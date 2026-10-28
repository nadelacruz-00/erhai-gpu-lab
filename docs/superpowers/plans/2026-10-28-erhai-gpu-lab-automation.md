# erhai-gpu-lab operator automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the ladder's hand-typed operator steps (mode switch, post-reboot g0, reset classification, g1 runs, g2 cycle counting, idle power, results) into a handful of `erhai-gpu-lab` subcommands, keeping the rEFInd kernel pick manual.

**Architecture:** `tablet/erhai-lab` (stdlib Python, installed as `/usr/local/sbin/erhai-gpu-lab`) gets new subcommands that drive the existing bash instruments (`tablet/gpu-checks.sh`, `tools/igt-recovery/igt-recovery`, `tablet/setup.sh`), now installed under `/usr/local/lib/erhai-gpu-lab/`. A oneshot unit runs `erhai-gpu-lab boot-run` on every boot: it logs the boot (kernel, candidate, how the previous boot ended) and, if a rung was queued for this kernel, runs it and saves the evidence. A disabled-by-default timer drives the g2 cycle counter. `tools/ship-candidate.sh` chains export → push → CI → fetch → queue on the dev side. All judgement logic is pure functions with unit tests; the wrappers only read sysfs/journal and call tools.

**Tech Stack:** Python 3 stdlib (`unittest`), bash, systemd units, `gh` CLI, trace-cmd, IGT `msm_recovery` (already wrapped by `tools/igt-recovery`, commit `8683622`).

**Spec:** `docs/ladder.md` (rungs g-1..g4, attribution rule, PON warm/cold method, idle-power method) and the design doc `/home/nadelacruz/.gstack/projects/TheMojoMan-oneplus-erhai-linux/nadelacruz-erhai-pps-dual-pump-design-20261027-171129.md`. User decisions 2026-10-28: automate the operator steps; **the kernel is picked by hand in rEFInd** (no `efibootmgr`/BootNext, no rEFInd config edits); g1 uses IGT `msm_recovery` (option A).

## Global Constraints

- Never change the boot selection: no `efibootmgr`, no writes to the ESP or rEFInd config. `fetch` keeps writing only `/boot/<lab kver>.efi` and `/usr/lib/modules/<lab kver>/`.
- Never read `/dev/mem` or use `devmem2` (it reset the tablet on 2026-10-28).
- Nothing hangs the GPU except `tools/igt-recovery/igt-recovery run`; `boot-run` and the soak timer never run g1.
- Paths: tool `/usr/local/sbin/erhai-gpu-lab`; helpers `/usr/local/lib/erhai-gpu-lab/{gpu-checks.sh,igt-recovery,setup.sh}`; state and evidence `/var/lib/erhai-gpu/`; IGT build `/var/lib/erhai-gpu/igt`; pin config `/etc/erhai/gpu-pin.conf`; battery `/sys/class/power_supply/erhai-adsp-bat/` (`voltage_now` µV, `current_now` µA, negative = discharging); GPU `/sys/devices/platform/soc@0/3d00000.gpu/power/control`.
- Pin services: `MODE=once` ⇔ `erhai-gpu-pin-once.service` enabled and `erhai-gpu-pin.service` disabled; `MODE=always` is the reverse. Changes take effect at the next boot.
- Reset classification (ladder, PON section): previous boot's journal ends with `Journal stopped` → `clean`; else if this boot's journal contains `erhai-rtc-sync: system clock is 1970` → `cold` (PMIC watchdog or power key, indistinguishable); else `warm` (expect a pstore record).
- Idle baseline: **3639 mW** (package kernel, `MODE=once`, 2026-10-28).
- Evidence must not depend on the wall clock: a cold reset starts the clock at 1970. Key records by `/proc/sys/kernel/random/boot_id`, not timestamps.
- Every subcommand that writes state or runs a tool needs root and says so (`require_root`); read-only `status`/`report` do not.
- Tools stay stdlib Python 3 / bash; tests run with `python3 -m unittest discover -s tests -v`; pure functions take paths/text as arguments so tests use temp dirs and fixture text.
- This repo is local-only today; publishing it (`gh repo create`, trailer scrub decision) is the operator's call and out of scope. `ship-candidate.sh` refuses to run without a remote.

## Review Focus

1. The operator picks the wrong kernel in rEFInd: a queued rung must not run or be consumed; the boot is logged and the queue kept for the next boot. Pinned by Task 3 test `test_boot_run_keeps_queue_on_wrong_kernel`.
2. `boot-run` failing must never wedge or delay boot indefinitely, and must still log the boot when no rung is queued. Pinned by Task 3 tests `test_boot_run_without_queue_only_logs` and the unit's `TimeoutStartSec=600` assertion.
3. A cold reset leaves the clock at 1970: soak totals and per-boot records must still be correct. Pinned by Task 5 test `test_soak_summary_ignores_clock` (records keyed by boot id).
4. Charger connected during `power`: V×I is then charge current, not idle draw. Pinned by Task 6 test `test_charging_sample_refuses`.
5. `/etc/erhai/gpu-pin.conf` missing or without a `MODE=` line: `mode` must refuse and leave the file untouched. Pinned by Task 2 test `test_set_mode_without_mode_line_refuses`.

---

### Task 1: Install helpers and the IGT build location

**Files:**
- Modify: `tablet/install.sh`, `tools/igt-recovery/igt-recovery` (default `IGT_DIR`), `tablet/erhai-lab` (constants, `setup` subcommand)
- Test: `tests/test_install_docs.py`, `tests/test_setup_sh.py`

**Interfaces:**
- Produces: constants in `tablet/erhai-lab`: `LIB_DIR = Path("/usr/local/lib/erhai-gpu-lab")`, `STATE_DIR = Path("/var/lib/erhai-gpu")`, `PIN_CONF = Path("/etc/erhai/gpu-pin.conf")`; `def helper(name: str) -> Path` returning `LIB_DIR / name` and raising `LabError("<name> not installed; run sudo tablet/install.sh")` if absent; subcommand `setup` (root): runs `helper("setup.sh")`, then `IGT_DIR=STATE_DIR/"igt" helper("igt-recovery") build`; non-zero exit of either → `LabError` naming the step.
- Produces: `install.sh install` copies `gpu-checks.sh`, `setup.sh` (from `tablet/`) and `igt-recovery` (from `tools/igt-recovery/`) into `LIB_DIR` mode 0755, and the units from Tasks 3 and 5 into `/etc/systemd/system/`, runs `systemctl daemon-reload` and `systemctl enable erhai-gpu-lab-boot.service` (the soak timer stays disabled). `uninstall` removes all of these (`systemctl disable --now` first), keeps `/var/lib/erhai-gpu`.

- [ ] **Step 1: Write failing tests**: `test_install_copies_helpers` asserts `install.sh` text contains `/usr/local/lib/erhai-gpu-lab`, `gpu-checks.sh`, `igt-recovery`, `setup.sh`, `erhai-gpu-lab-boot.service`, `systemctl enable erhai-gpu-lab-boot.service`, and does not contain `enable erhai-gpu-lab-soak.timer`; `test_igt_dir_defaults_to_state` asserts `IGT_DIR=${IGT_DIR:-/var/lib/erhai-gpu/igt}` in `igt-recovery`; `test_helper_missing_raises` (temp `LIB_DIR` via monkeypatching `lab.LIB_DIR`) asserts `LabError` with `"not installed"`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_install_docs tests.test_setup_sh -v`: the three new tests FAIL.
- [ ] **Step 3: Implement** the install/uninstall changes, the `IGT_DIR` default, the constants, `helper()` and `cmd_setup`. `install.sh` tolerates the Task 3/5 unit files being absent until those tasks land (`[ -f ] &&`).
- [ ] **Step 4: Run** the full suite: all PASS.
- [ ] **Step 5: Commit** `git commit -m "install: helpers under /usr/local/lib/erhai-gpu-lab; erhai-gpu-lab setup builds IGT"`

### Task 2: `mode once|always`

**Files:**
- Modify: `tablet/erhai-lab`
- Test: `tests/test_mode.py` (create)

**Interfaces:**
- Produces: `def read_mode(text: str) -> str` (last `MODE=` value; `LabError` if none); `def set_mode_text(text: str, mode: str) -> str` (replaces only the last uncommented `MODE=` line, everything else byte-identical; `LabError` for a mode other than `once`/`always` or no `MODE=` line); `def write_mode(conf: Path, mode: str, run=subprocess.run) -> None` (atomic: tmp file in the same dir + `os.replace`, keeps the file's mode bits, then the two `systemctl enable|disable` calls from Global Constraints via `run`); subcommand `mode {once,always}` prints `MODE=<mode> (was <old>); takes effect at the next boot`.

- [ ] **Step 1: Write failing tests** in `tests/test_mode.py` using the real comment block of `/etc/erhai/gpu-pin.conf` as a fixture string (copy it into `tests/fixtures/gpu-pin.conf`): `test_read_mode_once`; `test_set_mode_always_changes_only_mode_line` (diff of lines = exactly one line, `MODE=once`→`MODE=always`; the comment lines mentioning `MODE=always` untouched); `test_set_mode_without_mode_line_refuses` (comments only → `LabError`); `test_set_mode_rejects_unknown` (`"off"` → `LabError`); `test_write_mode_calls_systemctl` (fake `run` records calls; `always` → `["systemctl","enable","erhai-gpu-pin.service"]` and `["systemctl","disable","erhai-gpu-pin-once.service"]`; file in temp dir rewritten); `test_write_mode_failure_leaves_file` (unwritable temp dir → original content intact).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_mode -v`: FAIL (`read_mode` undefined).
- [ ] **Step 3: Implement** the three functions and `cmd_mode` (root).
- [ ] **Step 4: Run** the full suite: PASS.
- [ ] **Step 5: Commit** `git commit -m "erhai-gpu-lab mode: switch MODE and the pin services atomically"`

### Task 3: Boot log, reset kind, queued rungs (`queue`, `boot-run`, `status`)

**Files:**
- Modify: `tablet/erhai-lab`
- Create: `tablet/erhai-gpu-lab-boot.service`
- Test: `tests/test_boot_run.py` (create), fixtures `tests/fixtures/journal/{prev-clean.txt,prev-unclean.txt,cur-rtc-1970.txt,cur-normal.txt}` (prev-clean ends with the real tail captured 2026-10-28: `Received SIGTERM from PID 1 (systemd-shutdow).` / `Journal stopped`)

**Interfaces:**
- Produces: `def classify_prev_boot(prev_tail: str | None, cur_journal: str) -> str` → `"none"` (no previous boot), `"clean"`, `"cold"`, `"warm"` per Global Constraints.
- Produces: boots log `STATE_DIR/boots.log`, one line per boot, space-separated `key=value`: `boot=<boot_id> kver=<uname -r> cand=<candidate or package> build=<b> mode=<once|always> prev=<kind> pstore=<n files in /sys/fs/pstore>`; `def parse_boots(text: str) -> list[dict[str,str]]`.
- Produces: queue file `STATE_DIR/queue.json` `{"label": str, "expect": str}`, `expect` = a candidate name or `"package"`; subcommand `queue <label> --expect <cand|package>` (root, label must match `^g[0-9]+[a-z0-9-]*$`, only `g0` is runnable in this plan; others → `LabError("only g0 runs at boot")`); `def queue_matches(expect: str, cand: str) -> bool`.
- Produces: `def boot_run(state: Path, ident: dict, prev_tail: str | None, cur_journal: str, pstore_n: int, run_g0) -> str` — appends the boots.log line, then if a queue exists and matches, calls `run_g0(out_path)` with `out_path = state / f"{label}-{kver}-{boot_id[:8]}.txt"`, writes a header (`kver cand build stack mode prev`) before the checker's output, deletes the queue, returns `"ran <label> -> <path> (<PASS|FAIL>)"`; on mismatch returns `"queued <label> expects <x>, booted <y>; kept"`; no queue → `"logged"`. `cmd_boot_run` gathers inputs (`journalctl -b -1 -n 20 -o cat`, `journalctl -b -o cat`, `/proc/sys/kernel/random/boot_id`), calls it with `run_g0` = `helper("gpu-checks.sh") g0`, prints the result, and exits 0 even if g0 FAILs (the evidence file holds the verdict); an exception is printed and exits 1 without retrying.
- Produces: subcommand `status` (no root): `whoami` line, `MODE`, queue (or `none`), last 5 boots.log lines, newest 5 evidence files with their `PASS/FAIL` count.
- Produces: unit `erhai-gpu-lab-boot.service`: `Type=oneshot`, `After=graphical.target erhai-gpu-pin-once.service time-sync.target`, `WantedBy=graphical.target`, `ExecStart=/usr/local/sbin/erhai-gpu-lab boot-run`, `TimeoutStartSec=600` (g0's pin wait SETTLE+TIMEOUT=195 s plus SUSPEND_WAIT 60 s).

- [ ] **Step 1: Write failing tests**: `test_classify_clean`, `test_classify_cold_rtc_1970`, `test_classify_warm`, `test_classify_no_previous_boot` (`None` → `"none"`); `test_boot_run_without_queue_only_logs` (one boots.log line, `run_g0` not called, returns `"logged"`); `test_boot_run_runs_and_consumes_queue` (`expect="60-gpu-reference"`, ident cand matches, fake `run_g0` writes `PASS probe`/`FAIL zap`; evidence file has header and both lines, queue gone, return contains `FAIL`); `test_boot_run_keeps_queue_on_wrong_kernel` (expect candidate, booted package → queue still present, `run_g0` not called, boots.log line written); `test_queue_package_matches_only_package`; `test_queue_rejects_g1` (`LabError`); `test_parse_boots_roundtrip`; `test_unit_file` asserts the four unit lines above verbatim.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_boot_run -v`: FAIL.
- [ ] **Step 3: Implement** the functions, the three subcommands and the unit file.
- [ ] **Step 4: Run** the full suite: PASS.
- [ ] **Step 5: Commit** `git commit -m "erhai-gpu-lab: boot log with reset kind, queued g0 after a manual rEFInd pick"`

### Task 4: `g1` runner

**Files:**
- Modify: `tablet/erhai-lab`
- Test: `tests/test_g1.py` (create)

**Interfaces:**
- Consumes: `helper("igt-recovery")` (Task 1); its output contract: last line `PASS g1 <subtest>` or `FAIL g1 <subtest> ...`, exit 0/1/2.
- Produces: `def g1_plan(runs: int, hangcheck: int) -> list[str]` → `["gpu-fault"]*runs + ["hangcheck"]*hangcheck`; `def run_g1(plan: list[str], control: str, allow_pinned: bool, run_one, pause) -> tuple[bool, list[str]]` — refuses (`LabError("power/control is on; pass --pinned for the MODE=always run")`) when `control != "auto"` and not `allow_pinned`; runs each subtest via `run_one(sub) -> (rc, last_line)`, calls `pause(30)` between runs, stops at the first non-zero rc, returns `(all_passed, lines)`. Subcommand `g1 [--runs 5] [--hangcheck 1] [--pinned] [--yes]` (root): prints the ladder's freeze warning (keep an SSH session open; a broken kernel needs a power-key hold) and requires typing `yes` unless `--yes`; writes `STATE_DIR/g1-summary-<kver>-<boot_id[:8]>.txt` (header + lines); exit 0 all PASS, 1 otherwise. `--pinned` defaults to `--runs 1 --hangcheck 0` (the ladder's single `MODE=always` run).

- [ ] **Step 1: Write failing tests**: `test_g1_plan_default` (`5,1` → 5 gpu-fault then 1 hangcheck); `test_run_g1_refuses_pinned_control`; `test_run_g1_allows_pinned_with_flag`; `test_run_g1_stops_at_first_fail` (fake `run_one` fails on call 2 → 2 calls, `False`); `test_run_g1_pauses_between_not_after` (fake `pause` called `len(plan)-1` times with 30).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_g1 -v`: FAIL.
- [ ] **Step 3: Implement** `g1_plan`, `run_g1`, `cmd_g1`.
- [ ] **Step 4: Run** the full suite: PASS.
- [ ] **Step 5: Commit** `git commit -m "erhai-gpu-lab g1: run IGT msm_recovery per the ladder and stop at the first FAIL"`

### Task 5: `soak start|stop|status` (g2)

**Files:**
- Modify: `tablet/erhai-lab`
- Create: `tablet/erhai-gpu-lab-soak.service`, `tablet/erhai-gpu-lab-soak.timer`
- Test: `tests/test_soak.py` (create)

**Interfaces:**
- Consumes: `gpu-checks.sh cycles <secs>` output line `cycles=<n> suspend=<s> resume=<r>`; `parse_boots` (Task 3).
- Produces: `STATE_DIR/soak.json` `{"start_boot": <boot_id>, "start_line": <len of boots.log>}`; `STATE_DIR/soak-cycles.log` lines `boot=<id> secs=3000 cycles=<n>`; subcommands `soak start` (root: writes soak.json, empties soak-cycles.log, `systemctl enable --now erhai-gpu-lab-soak.timer`), `soak stop` (root: disables the timer, keeps the files), `soak tick` (run by the service: no soak.json → exit 0; else one `cycles 3000` window appended), `soak status` (no root).
- Produces: `WEDGE_RE = re.compile(r"GMU OOB|HFI .*timed out|hangcheck recover!|a8xx_recover|cx gdsc didn't collapse")`; `def soak_summary(cycles_log: str, boots: list[dict], start_line: int, kernel_logs: dict[str, str]) -> dict` → `{"hours": secs_total/3600, "cycles": int, "boots": int, "resets": [(boot, prev_kind)], "wedge_lines": [(boot, line)], "cycles_ok": cycles >= 1000}`, where boots = the start boot plus every boots.log line after `start_line`, a reset is a boot whose `prev` is `warm` or `cold`, and `kernel_logs` maps boot id → `journalctl -k -b <id> -o cat` text (gathered by `cmd_soak` only for those boots).
- Produces: timer `OnBootSec=5min`, `OnUnitActiveSec=55min`, `Unit=erhai-gpu-lab-soak.service`; service `Type=oneshot`, `ExecStart=/usr/local/sbin/erhai-gpu-lab soak tick`, `TimeoutStartSec=3300`.

- [ ] **Step 1: Write failing tests**: `test_soak_summary_counts_cycles_and_hours` (3 lines of 3000 s, 400 cycles each → 2.5 h, 1200, `cycles_ok`); `test_soak_summary_lists_resets_with_kind` (boots after start with `prev=cold` and `prev=clean` → one reset); `test_soak_summary_ignores_clock` (boots.log lines carry no timestamps; summary depends only on boot ids and line order; a boot before `start_line` is excluded); `test_soak_summary_collects_wedge_lines` (kernel log with `msm_dpu ... vblank timeout` and `hangcheck recover!` → only the latter); `test_tick_without_soak_is_noop`; `test_timer_and_service_files` asserts the unit lines above.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_soak -v`: FAIL.
- [ ] **Step 3: Implement** the summary, the four subcommands and the two unit files.
- [ ] **Step 4: Run** the full suite: PASS.
- [ ] **Step 5: Commit** `git commit -m "erhai-gpu-lab soak: g2 cycle counting across reboots, keyed by boot id"`

### Task 6: `power` (idle power, g4)

**Files:**
- Modify: `tablet/erhai-lab`
- Test: `tests/test_power.py` (create), fixture `tests/fixtures/idle-baseline.txt` (first 20 lines of `~/gpu-lab-evidence/idle-baseline.txt`: `<epoch> <µV> <µA>`)

**Interfaces:**
- Produces: `BASELINE_MW = 3639`; `def avg_discharge_mw(samples: list[tuple[int, int, int]]) -> float` = mean of `V*(-I)/1e9`; `LabError("charger connected (current_now >= 0 at <epoch>); unplug and rerun")` if any `I >= 0`; `LabError` for an empty list. Subcommand `power [--minutes 30]` (root: writes to `STATE_DIR`): samples every 10 s, writes `STATE_DIR/power-<kver>-<boot_id[:8]>.txt` in the fixture's format, prints `avg=<n> mW over <k> samples; baseline 3639 mW; candidate <= baseline: yes|no`. Prints the ladder's method (screen on, fixed brightness, Wi-Fi on, no apps) before starting.

- [ ] **Step 1: Write failing tests**: `test_avg_from_fixture` (matches a value computed independently in the test from the fixture with `statistics.mean`, to 0.1 mW); `test_charging_sample_refuses`; `test_empty_refuses`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_power -v`: FAIL.
- [ ] **Step 3: Implement** `avg_discharge_mw` and `cmd_power`.
- [ ] **Step 4: Run** the full suite: PASS.
- [ ] **Step 5: Commit** `git commit -m "erhai-gpu-lab power: idle V×I sampling against the 3639 mW baseline"`

### Task 7: `report`

**Files:**
- Modify: `tablet/erhai-lab`
- Test: `tests/test_report.py` (create)

**Interfaces:**
- Consumes: boots.log (Task 3), `g0-*`/`g1-summary-*`/`power-*` evidence files (Tasks 3, 4, 6), `soak_summary` (Task 5).
- Produces: `def render_report(state: Path, kernel_logs: dict[str, str] | None = None) -> str` — Markdown for pasting into `docs/ladder.md` Results: a boots table (`boot[:8] | kver | cand | mode | prev`), one section per g0 file (header, `PASS n / FAIL m / INFO k`, every FAIL line verbatim), each g1 summary verbatim, the soak summary if `soak.json` exists, each power result line. Missing files are skipped silently; an empty state dir yields `"No evidence in <dir>."`. Subcommand `report [--out FILE]` (no root; prints to stdout or writes FILE).

- [ ] **Step 1: Write failing tests**: `test_report_empty_state`; `test_report_g0_shows_fail_lines` (g0 file with 2 PASS, 1 FAIL, 1 INFO → counts line and the FAIL line verbatim); `test_report_boots_table` (2 boots.log lines → 2 table rows); `test_report_includes_g1_and_power`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_report -v`: FAIL.
- [ ] **Step 3: Implement** `render_report` and `cmd_report`.
- [ ] **Step 4: Run** the full suite: PASS.
- [ ] **Step 5: Commit** `git commit -m "erhai-gpu-lab report: Markdown of all evidence for the ladder Results"`

### Task 8: `tools/ship-candidate.sh` (export → CI → fetch → queue)

**Files:**
- Create: `tools/ship-candidate.sh`
- Test: `tests/test_ship_candidate.py` (create)

**Interfaces:**
- Consumes: `tools/export-patches.sh <kernel-dir> <branch> <candidate> [--prefix N]`; `erhai-gpu-lab fetch`/`queue` (Task 3).
- Produces: `tools/ship-candidate.sh <kernel-dir> <branch> <candidate> [--prefix N]`, run from the lab repo as the normal user. Order: refuse with exit 2 if the repo has no `origin` remote (`"no git remote; publish the lab repo first"`), if `gh auth status` fails, or if the tree has changes outside `candidates/<candidate>/`; run export-patches; if `candidates/<candidate>` changed, commit `candidates: <candidate> from <branch> @<12-char kernel sha>` and `git push`; find the `kernel` workflow run for `HEAD` (`gh run list --workflow kernel.yml --commit <sha> --json databaseId -q '.[0].databaseId'`, retry every 10 s up to 120 s); `gh run watch <id> --exit-status`; `sudo erhai-gpu-lab fetch <candidate>`; `sudo erhai-gpu-lab queue g0 --expect <candidate>`; final line `Reboot and pick <kver> in rEFInd; g0 runs by itself. Then: erhai-gpu-lab status`. Unchanged patches → skip commit/push and use the latest successful run for `HEAD`. Commit message has no trailer lines.

- [ ] **Step 1: Write failing tests**: `test_usage` (no args → exit 2, `usage` on stderr); `test_refuses_without_remote` (temp `git init` repo containing a copy of the script; exit 2, message as above); `test_refuses_dirty_tree` (remote set to a temp bare repo, an untracked file in `tablet/` → exit 2); `bash -n` passes; `test_no_trailers` (script text has no `Co-Authored-By`).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_ship_candidate -v`: FAIL.
- [ ] **Step 3: Implement** the script.
- [ ] **Step 4: Run** the full suite: PASS.
- [ ] **Step 5: Commit** `git commit -m "tools: ship-candidate.sh chains export, CI, fetch and the queued g0"`

### Task 9: Runbook in the ladder and README

**Files:**
- Modify: `docs/ladder.md` (new `## Runbook` section after Instruments; Rungs paragraph "A CP hang (shader loop)" → "A CP hang (IGT `msm_recovery`)"), `README.md` (How it works: `setup`, `status`, `report`)
- Test: `tests/test_install_docs.py`

**Interfaces:**
- Consumes: every subcommand above.
- Produces: the Runbook, one numbered line per rung with the exact commands: once: `sudo tablet/install.sh && sudo erhai-gpu-lab setup`; g0 candidate: `tools/ship-candidate.sh ~/Development/oneplus-erhai-linux erhai-gpu-reference 60-gpu-reference` → reboot, pick in rEFInd → `erhai-gpu-lab status`; g1 control on `lab-43`: `sudo erhai-gpu-lab g1 --runs 1 --hangcheck 0`; g1 candidate: `sudo erhai-gpu-lab g1`, then `sudo erhai-gpu-lab mode always`, reboot, `sudo erhai-gpu-lab g1 --pinned`, `sudo erhai-gpu-lab mode once`; g2: `sudo erhai-gpu-lab soak start` … `erhai-gpu-lab soak status` … `sudo erhai-gpu-lab soak stop`; g4 power: `sudo erhai-gpu-lab power`; results: `erhai-gpu-lab report`. States that the kernel is always picked by hand in rEFInd and nothing changes the default entry.

- [ ] **Step 1: Write failing test** `test_ladder_runbook` asserts `## Runbook`, `erhai-gpu-lab soak start`, `erhai-gpu-lab g1 --pinned`, `ship-candidate.sh`, `picked by hand in rEFInd` in the ladder and `erhai-gpu-lab report` in the README; asserts `shader loop` is absent from the ladder.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_install_docs -v`: FAIL.
- [ ] **Step 3: Write** the Runbook and README lines.
- [ ] **Step 4: Run** the full suite: PASS.
- [ ] **Step 5: Commit** `git commit -m "ladder: runbook with the erhai-gpu-lab commands per rung"`
