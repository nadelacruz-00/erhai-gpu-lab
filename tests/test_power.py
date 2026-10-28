# SPDX-License-Identifier: GPL-2.0-only
"""erhai-gpu-lab power: idle V*I averaging against the 3639 mW baseline."""

import argparse
import contextlib
import io
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from labtool import REPO_ROOT, lab

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "idle-baseline.txt"


def fixture_samples():
    return [tuple(int(x) for x in line.split())
            for line in FIXTURE.read_text().splitlines() if line.strip()]


class AvgDischargeTest(unittest.TestCase):
    def test_avg_from_fixture(self):
        samples = fixture_samples()
        self.assertEqual(len(samples), 20)
        want = statistics.mean(v * -i / 1e9 for _, v, i in samples)
        self.assertAlmostEqual(lab.avg_discharge_mw(samples), want, delta=0.1)
        self.assertEqual(lab.BASELINE_MW, 3639)

    def test_charging_sample_refuses(self):
        samples = fixture_samples()
        epoch, v, _ = samples[3]
        samples[3] = (epoch, v, 120000)
        with self.assertRaises(lab.LabError) as cm:
            lab.avg_discharge_mw(samples)
        self.assertEqual(str(cm.exception),
                         f"charger connected (current_now >= 0 at {epoch}); "
                         "unplug and rerun")

    def test_zero_current_refuses(self):
        with self.assertRaises(lab.LabError):
            lab.avg_discharge_mw([(1, 4000000, 0)])

    def test_empty_refuses(self):
        with self.assertRaises(lab.LabError):
            lab.avg_discharge_mw([])


class SampleTest(unittest.TestCase):
    def test_sample_battery_reads_and_sleeps_between(self):
        with tempfile.TemporaryDirectory() as tmp:
            bat = Path(tmp)
            (bat / "voltage_now").write_text("4000000\n")
            (bat / "current_now").write_text("-900000\n")
            sleeps = []
            out = lab.sample_battery(3, bat, sleep=sleeps.append,
                                     clock=iter([10, 20, 30]).__next__)
        self.assertEqual(out, [(10, 4000000, -900000), (20, 4000000, -900000),
                               (30, 4000000, -900000)])
        self.assertEqual(sleeps, [lab.POWER_INTERVAL_S] * 2)

    def test_format_samples_matches_fixture(self):
        self.assertEqual(lab.format_samples(fixture_samples()), FIXTURE.read_text())


class CmdPowerTest(unittest.TestCase):
    def run_power(self, minutes, samples):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "boot_id").write_text("abcdef01-2345-6789-abcd-ef0123456789\n")
            out = io.StringIO()
            with mock.patch.object(lab, "STATE_DIR", state), \
                 mock.patch.object(lab, "require_root"), \
                 mock.patch.object(lab, "sample_battery", return_value=samples) as sb, \
                 mock.patch.object(lab.os, "uname") as un, \
                 mock.patch.object(lab, "PROC_BOOT_ID", state / "boot_id"), \
                 contextlib.redirect_stdout(out):
                un.return_value.release = "7.3.0-test"
                rc = lab.cmd_power(argparse.Namespace(minutes=minutes))
            files = {p.name: p.read_text() for p in state.glob("power-*")}
            return rc, out.getvalue(), files, sb

    def test_writes_file_and_reports(self):
        samples = fixture_samples()
        rc, out, files, sb = self.run_power(2, samples)
        self.assertEqual(rc, 0)
        sb.assert_called_once()
        self.assertEqual(sb.call_args.args[0], 12)
        self.assertEqual(list(files), ["power-7.3.0-test-abcdef01.txt"])
        self.assertEqual(files["power-7.3.0-test-abcdef01.txt"], FIXTURE.read_text())
        avg = lab.avg_discharge_mw(samples)
        self.assertIn(f"avg={avg:.0f} mW over 20 samples; baseline 3639 mW; "
                      f"candidate <= baseline: {'yes' if avg <= 3639 else 'no'}", out)
        self.assertIn("screen on", out)

    def test_parser_default_minutes(self):
        args = lab.build_parser().parse_args(["power"])
        self.assertEqual(args.minutes, 30)
        self.assertIs(args.func, lab.cmd_power)


if __name__ == "__main__":
    unittest.main()
