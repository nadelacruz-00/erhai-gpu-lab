# SPDX-License-Identifier: GPL-2.0-only
"""erhai-gpu-lab report: Markdown of all evidence for the ladder Results."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from labtool import lab

A, B = "a" * 32, "b" * 32
K = "7.3.0-lab"

BOOT_A = f"boot={A} kver={K} cand=g0-x build=12 mode=once prev=clean pstore=0\n"
BOOT_B = f"boot={B} kver={K} cand=g0-x build=12 mode=always prev=warm pstore=1\n"
G0 = (f"# kver={K} cand=g0-x build=12 stack=s mode=once prev=clean\n"
      "PASS gpu-bound ok\nPASS pm-runtime ok\n"
      "FAIL gmu-idle GMU did not idle\nINFO note something\n")
G1_HEADER = lab.g1_header(K, "g0-x", "auto", ["gpu-fault", "hangcheck"])
POWER = "".join(f"{1000 + i} 4000000 -900000\n" for i in range(3))   # 3600 mW


class ReportTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)

    def put(self, name, text):
        (self.state / name).write_text(text)

    def test_report_empty_state(self):
        self.assertEqual(lab.render_report(self.state), f"No evidence in {self.state}.")

    def test_report_missing_state_dir(self):
        gone = self.state / "nope"
        self.assertEqual(lab.render_report(gone), f"No evidence in {gone}.")

    def test_report_g0_shows_fail_lines(self):
        self.put(f"g0-{K}-aaaaaaaa.txt", G0)
        out = lab.render_report(self.state)
        self.assertIn(f"g0-{K}-aaaaaaaa.txt", out)
        self.assertIn("PASS 2 / FAIL 1 / INFO 1", out)
        self.assertIn("FAIL gmu-idle GMU did not idle", out)
        self.assertNotIn("PASS gpu-bound", out)

    def test_report_boots_table(self):
        self.put("boots.log", BOOT_A + BOOT_B)
        out = lab.render_report(self.state)
        self.assertIn("| boot | kver | cand | mode | prev |", out)
        rows = [line for line in out.splitlines()
                if line.startswith("| ") and ("aaaaaaaa" in line or "bbbbbbbb" in line)]
        self.assertEqual(rows, [f"| aaaaaaaa | {K} | g0-x | once | clean |",
                                f"| bbbbbbbb | {K} | g0-x | always | warm |"])

    def test_report_boots_table_shows_prev_unknown(self):
        self.put("boots.log", BOOT_A.replace("prev=clean pstore=0",
                                             "prev=unknown pstore=0 unlogged=eeeeeeee"))
        self.assertIn(f"| aaaaaaaa | {K} | g0-x | once | unknown |",
                      lab.render_report(self.state))

    def test_report_includes_g1_and_power(self):
        self.put(f"g1-summary-{K}-aaaaaaaa.txt",
                 G1_HEADER + "\nPASS g1 gpu-fault\nPASS g1 hangcheck\nRESULT PASS\n")
        self.put(f"power-{K}-aaaaaaaa.txt", POWER)
        out = lab.render_report(self.state)
        self.assertIn(G1_HEADER, out)
        self.assertIn("PASS g1 hangcheck", out)
        self.assertIn("RESULT PASS", out)
        self.assertIn(f"power-{K}-aaaaaaaa.txt", out)
        self.assertIn("3600 mW", out)
        self.assertIn(f"baseline {lab.BASELINE_MW} mW", out)

    def test_report_g1_repeat_summaries_in_run_order(self):
        for name in ("", "-10", "-2"):
            self.put(f"g1-summary-{K}-12345678{name}.txt",
                     G1_HEADER + f"\nPASS g1 run{name or '-1'}\nRESULT PASS\n")
        out = lab.render_report(self.state)
        heads = [ln for ln in out.splitlines() if ln.startswith("### g1-summary")]
        self.assertEqual(heads, [f"### g1-summary-{K}-12345678.txt",
                                 f"### g1-summary-{K}-12345678-2.txt",
                                 f"### g1-summary-{K}-12345678-10.txt"])

    def test_report_g1_without_result_line_is_flagged(self):
        self.put(f"g1-summary-{K}-aaaaaaaa.txt", G1_HEADER + "\nPASS g1 gpu-fault\n")
        out = lab.render_report(self.state)
        self.assertIn("RESULT missing (froze or interrupted)", out)

    def test_report_ignores_g1_wrapper_logs(self):
        self.put(f"g1-gpu-fault-{K}-aaaaaaaa.txt", "WRAPPER-LOG-LINE\n")
        self.put(f"g1-hangcheck-{K}-aaaaaaaa.txt", "WRAPPER-LOG-LINE\n")
        self.assertEqual(lab.render_report(self.state), f"No evidence in {self.state}.")

    def test_report_power_error_is_printed_not_raised(self):
        self.put(f"power-{K}-aaaaaaaa.txt", "1 4000000 500000\n")
        out = lab.render_report(self.state)
        self.assertIn("charger connected", out)
        self.put(f"power-{K}-bbbbbbbb.txt", "")
        self.assertIn("no power samples", lab.render_report(self.state))

    def test_report_power_above_baseline(self):
        self.put(f"power-{K}-aaaaaaaa.txt", "1 4000000 -1000000\n")   # 4000 mW
        self.assertIn("candidate <= baseline: no", lab.render_report(self.state))

    def test_report_sections_in_order(self):
        self.put("boots.log", BOOT_A)
        self.put(f"g0-{K}-aaaaaaaa.txt", G0)
        self.put(f"g1-summary-{K}-aaaaaaaa.txt", G1_HEADER + "\nRESULT PASS\n")
        self.put("soak.json", json.dumps({"start_line": 1, "start_boot": A}))
        self.put(f"power-{K}-aaaaaaaa.txt", POWER)
        out = lab.render_report(self.state, {})
        heads = [line for line in out.splitlines() if line.startswith("## ")]
        self.assertEqual(heads, ["## Boots", "## g0", "## g1", "## Soak", "## Power"])

    def test_report_g0_files_sorted_by_name(self):
        self.put(f"g0-{K}-bbbbbbbb.txt", G0)
        self.put(f"g0-{K}-aaaaaaaa.txt", G0)
        out = lab.render_report(self.state)
        self.assertLess(out.index("aaaaaaaa.txt"), out.index("bbbbbbbb.txt"))


class ReportSoakTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        (self.state / "boots.log").write_text(BOOT_A + BOOT_B)
        (self.state / "soak.json").write_text(
            json.dumps({"start_line": 1, "start_boot": A}))
        (self.state / "soak-cycles.log").write_text(
            f"boot={A} secs=3600 cycles=600\nboot={B} secs=3600 cycles=500\n")

    def test_report_soak_summary_with_wedge_lines(self):
        logs = {B: "quiet\nmsm_dpu: GMU OOB timed out\n"}
        out = lab.render_report(self.state, logs)
        self.assertIn("hours: 2.00", out)
        self.assertIn("cycles: 1100 (>= 1000: yes)", out)
        self.assertIn("boots: 2", out)
        self.assertIn("reset bbbbbbbb warm", out)
        self.assertIn("wedge bbbbbbbb msm_dpu: GMU OOB timed out", out)
        self.assertNotIn("wedge lines not collected", out)

    def test_report_soak_without_kernel_logs_notes_it(self):
        out = lab.render_report(self.state, None)
        self.assertIn("cycles: 1100", out)
        self.assertIn("wedge lines not collected (run as root: erhai-gpu-lab report)", out)

    def test_report_soak_passes_start_boot(self):
        (self.state / "soak.json").write_text(
            json.dumps({"start_line": 1, "start_boot": B}))
        self.assertIn("boots: 1", lab.render_report(self.state, {}))

    def test_report_soak_honours_stop_line(self):
        (self.state / "soak.json").write_text(
            json.dumps({"start_line": 1, "start_boot": A, "stop_line": 1}))
        out = lab.render_report(self.state, {B: "GMU OOB timed out\n"})
        self.assertIn("boots: 1", out)
        self.assertNotIn("reset bbbbbbbb", out)
        self.assertNotIn("wedge bbbbbbbb", out)

    def test_report_corrupt_soak_json_is_reported(self):
        (self.state / "soak.json").write_text("{not json")
        self.assertIn("cannot read", lab.render_report(self.state, {}))


class CmdReportTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        (self.state / "boots.log").write_text(BOOT_A + BOOT_B)
        (self.state / "soak.json").write_text(
            json.dumps({"start_line": 1, "start_boot": A}))

    def run_cmd(self, argv, euid):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(lab, "STATE_DIR", self.state), \
                mock.patch.object(lab.os, "geteuid", return_value=euid), \
                mock.patch.object(lab, "_journal",
                                  return_value="GMU OOB timed out\n") as j, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = lab.main(argv)
        return rc, out.getvalue(), err.getvalue(), j

    def test_report_as_user_skips_journal(self):
        rc, out, _, j = self.run_cmd(["report"], 1000)
        self.assertEqual(rc, 0)
        j.assert_not_called()
        self.assertIn("wedge lines not collected", out)

    def test_report_as_root_collects_kernel_logs(self):
        rc, out, _, j = self.run_cmd(["report"], 0)
        self.assertEqual(rc, 0)
        j.assert_any_call("-k", "-b", A)
        self.assertIn("wedge aaaaaaaa GMU OOB timed out", out)

    def test_report_as_root_reads_only_the_soak_window(self):
        (self.state / "soak.json").write_text(
            json.dumps({"start_line": 1, "start_boot": A, "stop_line": 1}))
        _, _, _, j = self.run_cmd(["report"], 0)
        self.assertEqual(j.call_args_list, [mock.call("-k", "-b", A)])

    def test_report_out_file(self):
        dest = self.state / "report.md"
        rc, out, _, _ = self.run_cmd(["report", "--out", str(dest)], 1000)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")
        self.assertIn("## Boots", dest.read_text())

    def test_report_out_unwritable_is_lab_error(self):
        rc, _, err, _ = self.run_cmd(
            ["report", "--out", str(self.state / "no" / "r.md")], 1000)
        self.assertEqual(rc, 2)
        self.assertIn("erhai-lab: cannot write", err)


if __name__ == "__main__":
    unittest.main()
