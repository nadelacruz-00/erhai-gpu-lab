# SPDX-License-Identifier: GPL-2.0-only
"""erhai-gpu-lab soak: g2 runtime-PM cycle counting across reboots."""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from labtool import REPO_ROOT, lab

TABLET = REPO_ROOT / "tablet"
A, B, C, D = ("a" * 32, "b" * 32, "c" * 32, "d" * 32)


def boot(bid, prev="clean", **kw):
    return {"boot": bid, "kver": "7.3.0", "cand": "package", "build": "-",
            "mode": "once", "prev": prev, "pstore": "0", **kw}


def window(boot_id, cycles, secs=3000):
    return f"boot={boot_id} secs={secs} cycles={cycles}\n"


class SoakSummaryTest(unittest.TestCase):
    def test_soak_summary_counts_cycles_and_hours(self):
        log = window(A, 400) + window(A, 400) + window(B, 400)
        s = lab.soak_summary(log, [boot(A)], 1, {})
        self.assertAlmostEqual(s["hours"], 2.5)
        self.assertEqual(s["cycles"], 1200)
        self.assertTrue(s["cycles_ok"])

    def test_cycles_below_threshold(self):
        s = lab.soak_summary(window(A, 999), [boot(A)], 1, {})
        self.assertEqual(s["cycles"], 999)
        self.assertFalse(s["cycles_ok"])

    def test_empty_log(self):
        s = lab.soak_summary("", [boot(A)], 1, {})
        self.assertEqual((s["hours"], s["cycles"], s["cycles_ok"]), (0, 0, False))

    def test_malformed_lines_are_skipped(self):
        s = lab.soak_summary("garbage\n" + window(A, 10) + "boot=x secs=3000\n",
                             [boot(A)], 1, {})
        self.assertEqual((s["hours"], s["cycles"]), (3000 / 3600, 10))

    def test_soak_summary_lists_resets_with_kind(self):
        boots = [boot(A), boot(B, "cold"), boot(C, "clean")]
        s = lab.soak_summary(window(A, 1), boots, 1, {})
        self.assertEqual(s["resets"], [(B, "cold")])
        self.assertEqual(s["boots"], 3)

    def test_warm_is_a_reset(self):
        s = lab.soak_summary("", [boot(A), boot(B, "warm")], 1, {})
        self.assertEqual(s["resets"], [(B, "warm")])

    def test_soak_summary_ignores_clock(self):
        # boots.log lines carry no timestamps: only ids and line order matter,
        # and a boot before the start boot is not part of the soak
        boots = [boot(D, "cold"), boot(A), boot(B, "cold")]
        s = lab.soak_summary("", boots, 2, {D: "hangcheck recover!\n"})
        self.assertEqual(s["boots"], 2)
        self.assertEqual(s["resets"], [(B, "cold")])
        self.assertEqual(s["wedge_lines"], [])

    def test_start_boot_is_not_counted_twice(self):
        # soak start ran before boot-run logged its own boot
        boots = [boot(D), boot(A, "cold"), boot(B)]
        s = lab.soak_summary("", boots, 1, {}, start_boot=A)
        self.assertEqual(s["boots"], 2)
        self.assertEqual(lab.soak_boot_ids(boots, 1, A), [A, B])

    def test_soak_summary_counts_unlogged_resets(self):
        # C names two boots that froze before boot-run logged them
        boots = [boot(A), boot(B, "warm"), boot(C, "unknown", unlogged="11111111,22222222")]
        s = lab.soak_summary("", boots, 1, {})
        self.assertEqual(s["resets"], [(B, "warm"), ("11111111", "unlogged"),
                                       ("22222222", "unlogged")])
        self.assertEqual(s["boots"], 5)

    def test_start_boot_unlogged_predecessors_are_not_soak_resets(self):
        boots = [boot(D), boot(A, "unknown", unlogged="11111111"), boot(B)]
        s = lab.soak_summary("", boots, 2, {})
        self.assertEqual(s["resets"], [])
        self.assertEqual(s["boots"], 2)

    def test_stop_line_closes_the_window(self):
        boots = [boot(A), boot(B, "warm"), boot(C, "cold"), boot(D, "unknown", unlogged="11111111")]
        self.assertEqual(lab.soak_boot_ids(boots, 1, A, 2), [A, B])
        s = lab.soak_summary(window(A, 7), boots, 1, {C: "GMU OOB\n"}, A, 2)
        self.assertEqual(s["boots"], 2)
        self.assertEqual(s["resets"], [(B, "warm")])
        self.assertEqual(s["wedge_lines"], [])

    def test_soak_summary_collects_wedge_lines(self):
        klog = ("msm_dpu ae01000.display-controller: vblank timeout\n"
                "msm_dpu ae01000.display-controller: hangcheck recover! now\n")
        s = lab.soak_summary("", [boot(A), boot(B)], 1, {A: klog, B: "quiet\n"})
        self.assertEqual(s["wedge_lines"],
                         [(A, "msm_dpu ae01000.display-controller: hangcheck recover! now")])

    def test_wedge_re_patterns(self):
        for line in ("GMU OOB set failed", "HFI queue timed out",
                     "x hangcheck recover!", "a8xx_recover: x",
                     "cx gdsc didn't collapse"):
            self.assertTrue(lab.WEDGE_RE.search(line), line)
        self.assertFalse(lab.WEDGE_RE.search("vblank timeout"))


class StateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name)
        (self.state / "boot_id").write_text("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb\n")
        (self.state / "uptime").write_text("600.25 4000.00\n")
        for p in (mock.patch.object(lab, "STATE_DIR", self.state),
                  mock.patch.object(lab, "BOOT_ID_PATH", self.state / "boot_id"),
                  mock.patch.object(lab, "PROC_UPTIME", self.state / "uptime")):
            p.start()
            self.addCleanup(p.stop)

    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = lab.main(["soak", *argv])
        return rc, out.getvalue(), err.getvalue()


class TickTest(StateTest):
    def test_tick_without_soak_is_noop(self):
        with mock.patch.object(lab.subprocess, "run") as run:
            rc, _, _ = self.run_cmd("tick")
        self.assertEqual(rc, 0)
        run.assert_not_called()
        self.assertFalse((self.state / "soak-cycles.log").exists())

    def start_soak(self):
        (self.state / "soak.json").write_text(json.dumps({"start_boot": A, "start_line": 1}))

    def fake_run(self, stdout="", rc=0):
        return mock.patch.object(
            lab.subprocess, "run",
            return_value=subprocess.CompletedProcess([], rc, stdout, "boom\n"))

    def test_tick_appends_one_window_keyed_by_current_boot(self):
        self.start_soak()
        (self.state / "soak-cycles.log").write_text(window(A, 5))
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab, "helper", return_value=Path("/x/gpu-checks.sh")), \
             self.fake_run("cycles=412 suspend=412 resume=413\n") as run:
            rc, _, _ = self.run_cmd("tick")
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args.args[0], ["/x/gpu-checks.sh", "cycles", "600"])
        self.assertEqual((self.state / "soak-cycles.log").read_text(),
                         window(A, 5) + window(B, 412, secs=600))

    def test_tick_points_the_helper_at_the_live_file_and_removes_it(self):
        self.start_soak()
        (self.state / "soak-live.txt").write_text("started=1 cycles=3 suspend=3 resume=3\n")
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab, "helper", return_value=Path("/x/gpu-checks.sh")), \
             self.fake_run("cycles=412 suspend=412 resume=413\n") as run:
            self.run_cmd("tick")
        self.assertEqual(run.call_args.kwargs["env"]["CYCLES_LIVE"],
                         str(self.state / "soak-live.txt"))
        self.assertFalse((self.state / "soak-live.txt").exists())

    def test_failed_window_is_not_appended(self):
        self.start_soak()
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab, "helper", return_value=Path("/x/gpu-checks.sh")), \
             self.fake_run("", rc=1):
            rc, _, err = self.run_cmd("tick")
        self.assertEqual(rc, 1)
        self.assertIn("boom", err)
        self.assertFalse((self.state / "soak-cycles.log").exists())

    def test_unparsable_window_is_not_appended(self):
        self.start_soak()
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab, "helper", return_value=Path("/x/gpu-checks.sh")), \
             self.fake_run("no counters here\n"):
            rc, _, err = self.run_cmd("tick")
        self.assertEqual(rc, 1)
        self.assertIn("cycles=", err)
        self.assertFalse((self.state / "soak-cycles.log").exists())


class TickAfterStopTest(StateTest):
    def test_tick_after_stop_is_noop(self):
        (self.state / "soak.json").write_text(
            json.dumps({"start_boot": A, "start_line": 1, "stop_line": 2}))
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab.subprocess, "run") as run:
            rc, _, _ = self.run_cmd("tick")
        self.assertEqual(rc, 0)
        run.assert_not_called()
        self.assertFalse((self.state / "soak-cycles.log").exists())


class StartStopStatusTest(StateTest):
    def test_start_records_boot_and_line_and_enables_timer(self):
        (self.state / "boots.log").write_text(
            f"boot={A} prev=none pstore=0\nboot={B} prev=clean pstore=0\n")
        (self.state / "soak-cycles.log").write_text(window(A, 5))
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0)) as run:
            rc, _, _ = self.run_cmd("start")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads((self.state / "soak.json").read_text()),
                         {"start_boot": B, "start_line": 2, "start_uptime": 600.25})
        self.assertEqual((self.state / "soak-cycles.log").read_text(), "")
        run.assert_called_once_with(
            ["systemctl", "enable", "--now", "erhai-gpu-lab-soak.timer"])

    def test_start_without_boots_log(self):
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0)):
            self.run_cmd("start")
        self.assertEqual(json.loads((self.state / "soak.json").read_text()),
                         {"start_boot": B, "start_line": 0, "start_uptime": 600.25})

    def test_start_refuses_running_soak(self):
        running = json.dumps({"start_boot": A, "start_line": 1}) + "\n"
        (self.state / "soak.json").write_text(running)
        (self.state / "soak-cycles.log").write_text(window(A, 5))
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab.subprocess, "run") as run:
            rc, _, err = self.run_cmd("start")
        self.assertEqual(rc, 2)
        self.assertIn("soak already running; soak stop first", err)
        run.assert_not_called()
        self.assertEqual((self.state / "soak.json").read_text(), running)
        self.assertEqual((self.state / "soak-cycles.log").read_text(), window(A, 5))

    def test_start_after_stop_starts_a_new_soak(self):
        (self.state / "boots.log").write_text(f"boot={A} prev=none pstore=0\n")
        (self.state / "soak.json").write_text(
            json.dumps({"start_boot": A, "start_line": 0, "stop_line": 1}))
        (self.state / "soak-cycles.log").write_text(window(A, 5))
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0)):
            rc, _, _ = self.run_cmd("start")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads((self.state / "soak.json").read_text()),
                         {"start_boot": B, "start_line": 1, "start_uptime": 600.25})
        self.assertEqual((self.state / "soak-cycles.log").read_text(), "")

    def test_start_systemctl_failure_keeps_cycles_log(self):
        (self.state / "soak-cycles.log").write_text(window(A, 5))
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1)):
            rc, _, _ = self.run_cmd("start")
        self.assertEqual(rc, 2)
        self.assertEqual((self.state / "soak-cycles.log").read_text(), window(A, 5))

    def test_start_systemctl_failure_removes_soak_json(self):
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1)):
            rc, _, err = self.run_cmd("start")
        self.assertEqual(rc, 2)
        self.assertIn("erhai-gpu-lab-soak.timer", err)
        self.assertFalse((self.state / "soak.json").exists())

    def test_stop_disables_timer_and_keeps_files(self):
        (self.state / "soak.json").write_text("{}")
        (self.state / "soak-cycles.log").write_text(window(A, 5))
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0)) as run:
            rc, _, _ = self.run_cmd("stop")
        self.assertEqual(rc, 0)
        run.assert_called_once_with(
            ["systemctl", "disable", "--now", "erhai-gpu-lab-soak.timer"])
        self.assertTrue((self.state / "soak.json").exists())
        self.assertTrue((self.state / "soak-cycles.log").exists())

    def test_stop_records_stop_line(self):
        (self.state / "boots.log").write_text(
            f"boot={A} prev=none pstore=0\nboot={B} prev=clean pstore=0\n")
        (self.state / "soak.json").write_text(json.dumps({"start_boot": A, "start_line": 1}))
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0)):
            rc, _, _ = self.run_cmd("stop")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads((self.state / "soak.json").read_text()),
                         {"start_boot": A, "start_line": 1, "stop_line": 2})
        self.assertEqual([p.name for p in self.state.iterdir() if p.name.startswith(".")], [])

    def test_stop_again_keeps_the_first_stop_line(self):
        (self.state / "boots.log").write_text(
            f"boot={A} prev=none pstore=0\nboot={B} prev=clean pstore=0\n")
        (self.state / "soak.json").write_text(
            json.dumps({"start_boot": A, "start_line": 1, "stop_line": 1}))
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0)):
            self.run_cmd("stop")
        self.assertEqual(json.loads((self.state / "soak.json").read_text())["stop_line"], 1)

    def test_stop_without_soak_only_disables_timer(self):
        with mock.patch.object(lab, "require_root"), \
             mock.patch.object(lab.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0)) as run:
            rc, _, _ = self.run_cmd("stop")
        self.assertEqual(rc, 0)
        run.assert_called_once()
        self.assertFalse((self.state / "soak.json").exists())

    def test_status_after_stop_says_stopped_and_ignores_later_boots(self):
        (self.state / "soak.json").write_text(
            json.dumps({"start_boot": A, "start_line": 1, "stop_line": 1}))
        (self.state / "boots.log").write_text(
            f"boot={A} prev=none pstore=0\nboot={B} prev=cold pstore=0\n")
        with mock.patch.object(lab, "_journal", return_value=None) as j:
            rc, out, _ = self.run_cmd("status")
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        self.assertIn("soak: stopped", lines)
        self.assertIn("boots: 1", lines)
        self.assertNotIn("reset bbbbbbbb cold", lines)
        self.assertEqual(j.call_args_list, [mock.call("-k", "-b", A)])

    def test_root_commands_refuse_without_root(self):
        with mock.patch.object(lab.os, "geteuid", return_value=1000), \
             mock.patch.object(lab.subprocess, "run") as run:
            for cmd in ("start", "stop"):
                rc, _, err = self.run_cmd(cmd)
                self.assertEqual(rc, 2)
                self.assertIn("needs root", err)
        run.assert_not_called()

    def test_status_without_soak(self):
        rc, out, _ = self.run_cmd("status")
        self.assertEqual(rc, 0)
        self.assertIn("no soak", out)

    def test_status_prints_summary(self):
        (self.state / "soak.json").write_text(json.dumps({"start_boot": A, "start_line": 1}))
        (self.state / "boots.log").write_text(
            f"boot={A} prev=none pstore=0\nboot={B} prev=cold pstore=0\n")
        (self.state / "soak-cycles.log").write_text(window(A, 600) + window(A, 500))
        calls = []

        def journal(*args):
            calls.append(args)
            return "x hangcheck recover! y\n" if args[2] == B else None

        with mock.patch.object(lab, "_journal", side_effect=journal):
            rc, out, _ = self.run_cmd("status")
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [("-k", "-b", A), ("-k", "-b", B)])
        lines = out.splitlines()
        self.assertIn("soak: running", lines)
        self.assertIn("hours: 1.67", lines)
        self.assertIn("cycles: 1100 (>= 1000: yes)", lines)
        self.assertIn("boots: 2", lines)
        self.assertIn("reset bbbbbbbb cold", lines)
        self.assertIn("wedge bbbbbbbb x hangcheck recover! y", lines)

    def test_status_shows_the_running_window(self):
        (self.state / "soak.json").write_text(json.dumps({"start_boot": A, "start_line": 1}))
        (self.state / "soak-cycles.log").write_text(window(A, 129, secs=600))
        (self.state / "soak-live.txt").write_text("started=1 cycles=57 suspend=58 resume=57\n")
        with mock.patch.object(lab, "_journal", return_value=None):
            rc, out, _ = self.run_cmd("status")
        self.assertEqual(rc, 0)
        self.assertIn("cycles: 129 (>= 1000: no)", out.splitlines())
        self.assertRegex(out, r"(?m)^live: \+57 cycles in the running window \(updated \d+ s ago\)$")

    def test_status_without_live_file_has_no_live_line(self):
        (self.state / "soak.json").write_text(json.dumps({"start_boot": A, "start_line": 1}))
        with mock.patch.object(lab, "_journal", return_value=None):
            _, out, _ = self.run_cmd("status")
        self.assertNotIn("live:", out)

    def test_parser_shape(self):
        p = lab.build_parser()
        for sub in ("start", "stop", "tick", "status"):
            self.assertEqual(p.parse_args(["soak", sub]).soak_cmd, sub)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            p.parse_args(["soak"])


class UnitFilesTest(unittest.TestCase):
    def test_timer_and_service_files(self):
        timer = (TABLET / "erhai-gpu-lab-soak.timer").read_text().splitlines()
        service = (TABLET / "erhai-gpu-lab-soak.service").read_text().splitlines()
        for line in ("OnBootSec=5min", "OnUnitActiveSec=11min",
                     "Unit=erhai-gpu-lab-soak.service"):
            self.assertIn(line, timer)
        for line in ("Type=oneshot",
                     "ExecStart=/usr/local/sbin/erhai-gpu-lab soak tick",
                     "TimeoutStartSec=900"):
            self.assertIn(line, service)
        self.assertNotIn("[Install]", "\n".join(service))


if __name__ == "__main__":
    unittest.main()


class StartBootTrimTest(unittest.TestCase):
    """Rungs run before `soak start` in the same boot (g1's induced hangs) are
    not soak wedges; later boots count whole."""

    MONO = ("[  120.000001] tabby-boi kernel: msm_dpu ae01000.display-controller: [drm:recover_worker] *ERROR* 44050001: hangcheck recover!\n"
            "[  599.999999] tabby-boi kernel: before the start\n"
            "[  600.250000] tabby-boi kernel: at the start\n"
            "[ 4100.5] tabby-boi kernel: platform 3d37000.gmu: [drm:a6xx_gmu_set_oob] *ERROR* Timeout waiting for GMU OOB set GPU_SET: 0x0\n")

    def test_messages_since_keeps_only_later_lines(self):
        out = lab.messages_since(self.MONO, 600.25)
        self.assertEqual(out.splitlines(), [
            "at the start",
            "platform 3d37000.gmu: [drm:a6xx_gmu_set_oob] *ERROR* Timeout waiting for GMU OOB set GPU_SET: 0x0"])

    def test_messages_since_nothing_later(self):
        self.assertEqual(lab.messages_since(self.MONO, 9999), "")

    def test_soak_kernel_logs_trims_only_the_start_boot(self):
        calls = []

        def fake(*args, fmt="cat"):
            calls.append((args, fmt))
            return self.MONO if fmt == "short-monotonic" else "whole log of " + args[-1]
        soak = {"start_boot": A, "start_line": 1, "start_uptime": 600.25}
        with mock.patch.object(lab, "_journal", side_effect=fake):
            logs = lab.soak_kernel_logs(soak, [A, B])
        self.assertNotIn("hangcheck recover!", logs[A])
        self.assertIn("GPU_SET", logs[A])
        self.assertEqual(logs[B], "whole log of " + B)
        self.assertEqual(calls, [(("-k", "-b", A), "short-monotonic"), (("-k", "-b", B), "cat")])

    def test_soak_without_start_uptime_reads_whole_logs(self):
        with mock.patch.object(lab, "_journal", return_value="x\n") as j:
            logs = lab.soak_kernel_logs({"start_boot": A, "start_line": 1}, [A])
        self.assertEqual(logs, {A: "x\n"})
        j.assert_called_once_with("-k", "-b", A)
