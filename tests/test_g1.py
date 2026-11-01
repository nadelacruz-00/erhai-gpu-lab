# SPDX-License-Identifier: GPL-2.0-only
"""erhai-gpu-lab g1: ladder plan, stop-at-first-FAIL runner, arg defaults."""

import argparse
import contextlib
import io
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from labtool import lab


class G1PlanTest(unittest.TestCase):
    def test_g1_plan_default(self):
        self.assertEqual(lab.g1_plan(5, 1), ["gpu-fault"] * 5 + ["hangcheck"])

    def test_g1_plan_zero_hangcheck(self):
        self.assertEqual(lab.g1_plan(1, 0), ["gpu-fault"])


class RunG1Test(unittest.TestCase):
    def test_run_g1_refuses_pinned_control(self):
        calls = []
        with self.assertRaisesRegex(lab.LabError, "power/control is on"):
            lab.run_g1(["gpu-fault"], "on", False,
                       lambda s: calls.append(s) or (0, "PASS"), lambda n: None)
        self.assertEqual(calls, [])

    def test_run_g1_allows_pinned_with_flag(self):
        ok, lines = lab.run_g1(["gpu-fault"], "on", True,
                               lambda s: (0, f"PASS g1 {s}"), lambda n: None)
        self.assertTrue(ok)
        self.assertEqual(lines, ["PASS g1 gpu-fault"])

    def test_run_g1_stops_at_first_fail(self):
        calls = []

        def run_one(sub):
            calls.append(sub)
            return (0, "PASS g1 x") if len(calls) == 1 else (1, "FAIL g1 x (bad)")

        ok, lines = lab.run_g1(["gpu-fault"] * 5, "auto", False, run_one,
                               lambda n: None)
        self.assertFalse(ok)
        self.assertEqual(len(calls), 2)
        self.assertEqual(lines, ["PASS g1 x", "FAIL g1 x (bad)"])

    def test_run_g1_pauses_between_not_after(self):
        plan = ["gpu-fault"] * 3 + ["hangcheck"]
        pauses = []
        ok, _ = lab.run_g1(plan, "auto", False, lambda s: (0, "PASS"),
                           pauses.append)
        self.assertTrue(ok)
        self.assertEqual(pauses, [30] * (len(plan) - 1))

    def test_run_g1_no_pause_after_fail(self):
        pauses = []
        lab.run_g1(["gpu-fault"] * 3, "auto", False, lambda s: (1, "FAIL"),
                   pauses.append)
        self.assertEqual(pauses, [])


class G1ArgsTest(unittest.TestCase):
    def parse(self, *argv):
        return lab.build_parser().parse_args(["g1", *argv])

    def test_defaults(self):
        self.assertEqual(lab.g1_counts(self.parse()), (5, 1))

    def test_pinned_changes_defaults(self):
        self.assertEqual(lab.g1_counts(self.parse("--pinned")), (1, 0))

    def test_explicit_wins_over_pinned(self):
        self.assertEqual(lab.g1_counts(self.parse("--pinned", "--runs", "3")), (3, 0))
        self.assertEqual(lab.g1_counts(self.parse("--pinned", "--hangcheck", "2")), (1, 2))
        self.assertEqual(lab.g1_counts(self.parse("--runs", "2")), (2, 1))


class LastLineTest(unittest.TestCase):
    def test_last_nonempty_line(self):
        self.assertEqual(lab.last_nonempty(["a\n", "PASS g1 x\n", "\n", "  \n"]),
                         "PASS g1 x")
        self.assertEqual(lab.last_nonempty([]), "")


class SummaryTest(unittest.TestCase):
    def test_header(self):
        self.assertEqual(lab.g1_header("7.3.0-lab", "cand-a", "auto",
                                       ["gpu-fault", "hangcheck"]),
                         "# kver=7.3.0-lab cand=cand-a control=auto plan=gpu-fault,hangcheck")

    def test_result_line_no_output(self):
        self.assertEqual(lab.g1_result_line("gpu-fault", 2, ""),
                         "FAIL g1 gpu-fault (no result line, rc=2)")

    def test_result_line_pass_with_bad_rc(self):
        self.assertEqual(lab.g1_result_line("gpu-fault", 1, "PASS g1 gpu-fault"),
                         "PASS g1 gpu-fault (rc=1)")

    def test_result_line_passthrough(self):
        self.assertEqual(lab.g1_result_line("x", 0, "PASS g1 x"), "PASS g1 x")
        self.assertEqual(lab.g1_result_line("x", 1, "FAIL g1 x (bad)"), "FAIL g1 x (bad)")


class ConfirmTest(unittest.TestCase):
    def test_confirm_requires_exact_yes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            lab.g1_confirm(lambda: "yes\n")
            for bad in ("y\n", "YES\n", "no\n", "\n", ""):
                with self.assertRaisesRegex(lab.LabError, "aborted"):
                    lab.g1_confirm(lambda bad=bad: bad)

    def test_confirm_prints_warning(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            lab.g1_confirm(lambda: "yes\n")
        self.assertIn("SSH", out.getvalue())
        self.assertIn("power", out.getvalue())


class RunOneTest(unittest.TestCase):
    def test_run_one_streams_and_returns_rc_and_last_line(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "igt-recovery"
            fake.write_text('#!/bin/sh\necho "igt-recovery: $1 start"\n'
                            'echo "FAIL g1 $2"\necho\nexit 1\n')
            fake.chmod(0o755)
            out = io.StringIO()
            with mock.patch.object(lab, "helper", return_value=fake), \
                 contextlib.redirect_stdout(out):
                rc, last = lab.run_one("hangcheck")
            self.assertEqual((rc, last), (1, "FAIL g1 hangcheck"))
            self.assertIn("igt-recovery: run start", out.getvalue())


class RunOneVerdictTest(unittest.TestCase):
    """A zero exit without a PASS line is a failure: the loop stops, RESULT FAIL."""

    def run_fake(self, body):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "igt-recovery"
            fake.write_text("#!/bin/sh\n" + body)
            fake.chmod(0o755)
            with mock.patch.object(lab, "helper", return_value=fake), \
                 contextlib.redirect_stdout(io.StringIO()):
                return lab.run_one("gpu-fault")

    def test_fail_line_with_zero_exit_is_rc_1(self):
        self.assertEqual(self.run_fake('echo "FAIL g1 gpu-fault (recover=2)"\nexit 0\n'),
                         (1, "FAIL g1 gpu-fault (recover=2)"))

    def test_no_line_with_zero_exit_is_rc_1(self):
        self.assertEqual(self.run_fake("exit 0\n"),
                         (1, "FAIL g1 gpu-fault (no result line, rc=0)"))

    def test_pass_line_with_zero_exit_stays_rc_0(self):
        self.assertEqual(self.run_fake('echo "PASS g1 gpu-fault"\n'),
                         (0, "PASS g1 gpu-fault"))


class RunOneNoLineTest(unittest.TestCase):
    def test_run_one_records_missing_result_line(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "igt-recovery"
            fake.write_text("#!/bin/sh\nexit 2\n")
            fake.chmod(0o755)
            with mock.patch.object(lab, "helper", return_value=fake), \
                 contextlib.redirect_stdout(io.StringIO()):
                rc, last = lab.run_one("gpu-fault")
            self.assertEqual((rc, last), (2, "FAIL g1 gpu-fault (no result line, rc=2)"))


class SummaryPathTest(unittest.TestCase):
    def test_first_free_summary_name(self):
        with tempfile.TemporaryDirectory() as d:
            state = Path(d)
            base = state / "g1-summary-7.3.0-lab-12345678.txt"
            self.assertEqual(lab.g1_summary_path(state, "7.3.0-lab", "12345678"), base)
            base.write_text("first\n")
            self.assertEqual(lab.g1_summary_path(state, "7.3.0-lab", "12345678"),
                             state / "g1-summary-7.3.0-lab-12345678-2.txt")
            (state / "g1-summary-7.3.0-lab-12345678-2.txt").write_text("second\n")
            self.assertEqual(lab.g1_summary_path(state, "7.3.0-lab", "12345678"),
                             state / "g1-summary-7.3.0-lab-12345678-3.txt")


class CmdG1Test(unittest.TestCase):
    def args(self, *argv):
        return lab.build_parser().parse_args(["g1", *argv])

    @contextlib.contextmanager
    def env(self, run_one):
        with tempfile.TemporaryDirectory() as d:
            boot = Path(d) / "boot_id"
            boot.write_text("12345678-aaaa-bbbb-cccc-dddddddddddd\n")
            ctl = Path(d) / "control"
            ctl.write_text("auto\n")
            cmdline = Path(d) / "cmdline"
            cmdline.write_text("erhai_lab.candidate=cand-a\n")
            with mock.patch.object(lab.os, "geteuid", return_value=0), \
                 mock.patch.object(lab, "STATE_DIR", Path(d)), \
                 mock.patch.object(lab, "BOOT_ID_PATH", boot), \
                 mock.patch.object(lab, "GPU_CONTROL", ctl), \
                 mock.patch.object(lab, "PROC_CMDLINE", cmdline), \
                 mock.patch.object(lab.os, "uname",
                                   return_value=mock.Mock(release="7.3.0-lab")), \
                 mock.patch.object(lab, "helper", return_value=Path("/x/igt-recovery")), \
                 mock.patch.object(lab, "run_one", run_one), \
                 mock.patch.object(lab.time, "sleep"), \
                 contextlib.redirect_stdout(io.StringIO()):
                yield Path(d) / "g1-summary-7.3.0-lab-12345678.txt"

    def test_cmd_g1_needs_root(self):
        with mock.patch.object(lab.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(lab.LabError, "needs root"):
                lab.cmd_g1(self.args("--yes"))

    def test_cmd_g1_writes_summary_and_exit_code(self):
        run_one = mock.Mock(side_effect=[(0, "PASS g1 gpu-fault"),
                                         (1, "FAIL g1 gpu-fault (x)")])
        with self.env(run_one) as summary:
            rc = lab.cmd_g1(self.args("--yes", "--runs", "3", "--hangcheck", "0"))
            self.assertEqual(rc, 1)
            self.assertEqual(summary.read_text().splitlines(), [
                "# kver=7.3.0-lab cand=cand-a control=auto plan=gpu-fault,gpu-fault,gpu-fault",
                "PASS g1 gpu-fault", "FAIL g1 gpu-fault (x)", "RESULT FAIL"])

    def test_cmd_g1_all_pass(self):
        with self.env(lambda s: (0, f"PASS g1 {s}")) as summary:
            rc = lab.cmd_g1(self.args("--yes", "--runs", "2", "--hangcheck", "1"))
            self.assertEqual(rc, 0)
            self.assertEqual(summary.read_text().splitlines()[-1], "RESULT PASS")

    def test_cmd_g1_second_run_same_boot_keeps_first_summary(self):
        with self.env(lambda s: (0, f"PASS g1 {s}")) as summary:
            lab.cmd_g1(self.args("--yes", "--runs", "1", "--hangcheck", "0"))
            first = summary.read_text()
            lab.cmd_g1(self.args("--yes", "--runs", "2", "--hangcheck", "0"))
            self.assertEqual(summary.read_text(), first)
            second = summary.with_name("g1-summary-7.3.0-lab-12345678-2.txt")
            self.assertEqual(second.read_text().splitlines(), [
                "# kver=7.3.0-lab cand=cand-a control=auto plan=gpu-fault,gpu-fault",
                "PASS g1 gpu-fault", "PASS g1 gpu-fault", "RESULT PASS"])

    def test_cmd_g1_interrupt_leaves_partial_summary_without_result(self):
        calls = []

        def run_one(sub):
            calls.append(sub)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return 0, "PASS g1 gpu-fault"

        with self.env(run_one) as summary:
            with self.assertRaises(KeyboardInterrupt):
                lab.cmd_g1(self.args("--yes", "--runs", "3", "--hangcheck", "0"))
            lines = summary.read_text().splitlines()
            self.assertEqual(lines, [
                "# kver=7.3.0-lab cand=cand-a control=auto plan=gpu-fault,gpu-fault,gpu-fault",
                "PASS g1 gpu-fault"])
            self.assertFalse(any(l.startswith("RESULT") for l in lines))

    def test_cmd_g1_abort_runs_nothing_and_writes_no_summary(self):
        run_one = mock.Mock()
        with self.env(run_one) as summary:
            with mock.patch.object(lab.sys, "stdin", io.StringIO("no\n")):
                with self.assertRaisesRegex(lab.LabError, "aborted"):
                    lab.cmd_g1(self.args())
            run_one.assert_not_called()
            self.assertFalse(summary.exists())
            self.assertEqual(list(summary.parent.glob("g1-summary-*")), [])


class DumpCheckTest(unittest.TestCase):
    """igt-recovery dump-check <marker>: saved devcoredump completeness."""

    FULL = "ringbuffer:\ngmu-log:\ngmu-hfi:\nqueue-history[0]:\n"
    SCRIPT = str(Path(__file__).resolve().parent.parent / "tools/igt-recovery/igt-recovery")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.d = Path(self._tmp.name)
        self.dumps = self.d / "coredumps"
        self.dumps.mkdir()
        self.marker = self.d / "marker"
        self.marker.write_text("")
        os.utime(self.marker, (1000, 1000))
        self.dbg = self.d / "dbg" / "gpu"
        self.dbg.parent.mkdir()
        self.dbg.write_text(self.FULL)

    def bin(self, text, mtime=2000, name="aaaaaaaa-1.bin"):
        f = self.dumps / name
        f.write_text(text)
        os.utime(f, (mtime, mtime))

    def check(self, wait="1", glob=None):
        env = dict(os.environ, ERHAI_COREDUMP_DIR=str(self.dumps),
                   ERHAI_DUMP_WAIT_S=wait,
                   ERHAI_DEBUGFS_GPU_GLOB=glob or str(self.dbg))
        t = time.monotonic()
        r = subprocess.run(["bash", self.SCRIPT, "dump-check", str(self.marker)],
                           env=env, capture_output=True, text=True)
        return r.returncode, r.stdout, time.monotonic() - t

    def test_dump_check_ok(self):
        self.bin(self.FULL)
        rc, out, _ = self.check()
        self.assertEqual((rc, out), (0, "dump=ok\n"))

    def test_dump_check_reports_missing_bin(self):
        # IGT's read_and_clear_devcore may consume the devcd before the copier.
        rc, out, dt = self.check()
        self.assertEqual((rc, out), (0, "dump=debugfs-only\n"))
        self.assertLess(dt, 3)

    def test_dump_check_missing_bin_and_debugfs_fails(self):
        rc, out, _ = self.check(glob=str(self.d / "nothing*" / "gpu"))
        self.assertEqual((rc, out), (1, "dump=incomplete:debugfs\n"))

    def test_dump_check_reports_incomplete(self):
        self.bin(self.FULL.replace("gmu-hfi:\n", ""))
        rc, out, _ = self.check()
        self.assertEqual((rc, out), (1, "dump=incomplete:gmu-hfi\n"))

    def test_old_bin_is_ignored(self):
        self.bin(self.FULL, mtime=500)
        rc, out, _ = self.check()
        self.assertEqual((rc, out), (0, "dump=debugfs-only\n"))

    def test_dump_check_uses_newest_bin(self):
        self.bin("ringbuffer:\n", mtime=1500, name="aaaaaaaa-1.bin")
        self.bin(self.FULL, mtime=2500, name="aaaaaaaa-2.bin")
        rc, out, _ = self.check()
        self.assertEqual((rc, out), (0, "dump=ok\n"))

    def test_dump_check_reports_missing_debugfs(self):
        self.bin(self.FULL)
        rc, out, _ = self.check(glob=str(self.d / "nothing*" / "gpu"))
        self.assertEqual((rc, out), (1, "dump=incomplete:debugfs\n"))

    def test_dump_check_reports_incomplete_debugfs(self):
        self.bin(self.FULL)
        self.dbg.write_text("ringbuffer:\ngmu-log:\n")
        rc, out, _ = self.check()
        self.assertEqual((rc, out), (1, "dump=incomplete:debugfs-gmu-hfi\n"))


if __name__ == "__main__":
    unittest.main()
