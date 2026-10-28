# SPDX-License-Identifier: GPL-2.0-only
"""erhai-gpu-lab mode once|always: MODE rewrite and the two pin services."""

import argparse
import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from labtool import REPO_ROOT, lab

FIXTURE = (REPO_ROOT / "tests" / "fixtures" / "gpu-pin.conf").read_text()


class FakeRun:
    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, cmd, *a, **kw):
        self.calls.append(list(cmd))
        rc = 1 if self.fail_on and list(cmd) == self.fail_on else 0
        return subprocess.CompletedProcess(cmd, rc)


class ModeText(unittest.TestCase):
    def test_read_mode_once(self):
        self.assertEqual(lab.read_mode(FIXTURE), "once")

    def test_read_mode_ignores_comments(self):
        # the fixture's comments mention MODE=always; only the real line counts
        self.assertIn("# MODE=always", FIXTURE)
        self.assertEqual(lab.read_mode(FIXTURE), "once")

    def test_read_mode_without_line_refuses(self):
        with self.assertRaises(lab.LabError):
            lab.read_mode("# MODE=once\n# nothing else\n")

    def test_set_mode_always_changes_only_mode_line(self):
        out = lab.set_mode_text(FIXTURE, "always")
        old, new = FIXTURE.split("\n"), out.split("\n")
        self.assertEqual(len(old), len(new))
        diff = [(a, b) for a, b in zip(old, new) if a != b]
        self.assertEqual(diff, [("MODE=once", "MODE=always")])
        self.assertEqual(lab.read_mode(out), "always")

    def test_set_mode_round_trips_byte_identical(self):
        self.assertEqual(
            lab.set_mode_text(lab.set_mode_text(FIXTURE, "always"), "once"), FIXTURE)

    def test_set_mode_without_mode_line_refuses(self):
        with self.assertRaises(lab.LabError):
            lab.set_mode_text("# MODE=once\n# MODE=always\nSETTLE=15\n", "always")

    def test_set_mode_rejects_unknown(self):
        with self.assertRaises(lab.LabError):
            lab.set_mode_text(FIXTURE, "off")


class WriteMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.conf = self.dir / "gpu-pin.conf"
        self.conf.write_text(FIXTURE)
        self.conf.chmod(0o640)

    def tearDown(self):
        os.chmod(self.dir, 0o755)
        self.tmp.cleanup()

    def test_write_mode_calls_systemctl(self):
        run = FakeRun()
        lab.write_mode(self.conf, "always", run=run)
        self.assertEqual(run.calls, [
            ["systemctl", "enable", "erhai-gpu-pin.service"],
            ["systemctl", "disable", "erhai-gpu-pin-once.service"]])
        self.assertEqual(lab.read_mode(self.conf.read_text()), "always")
        self.assertEqual(self.conf.read_text(),
                         lab.set_mode_text(FIXTURE, "always"))
        self.assertEqual(stat.S_IMODE(self.conf.stat().st_mode), 0o640)
        self.assertEqual(os.listdir(self.dir), ["gpu-pin.conf"])  # no tmp left

    def test_write_mode_once_reverses_the_services(self):
        run = FakeRun()
        lab.write_mode(self.conf, "once", run=run)
        self.assertEqual(run.calls, [
            ["systemctl", "enable", "erhai-gpu-pin-once.service"],
            ["systemctl", "disable", "erhai-gpu-pin.service"]])

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_write_mode_failure_leaves_file(self):
        os.chmod(self.dir, 0o555)
        run = FakeRun()
        with self.assertRaises(lab.LabError):
            lab.write_mode(self.conf, "always", run=run)
        self.assertEqual(self.conf.read_text(), FIXTURE)
        self.assertEqual(run.calls, [])  # no systemctl after a failed write

    def test_write_mode_rejects_unknown_before_touching_anything(self):
        run = FakeRun()
        with self.assertRaises(lab.LabError):
            lab.write_mode(self.conf, "off", run=run)
        self.assertEqual(self.conf.read_text(), FIXTURE)
        self.assertEqual(run.calls, [])

    def test_systemctl_failure_names_command_and_rewritten_file(self):
        run = FakeRun(fail_on=["systemctl", "disable", "erhai-gpu-pin-once.service"])
        with self.assertRaises(lab.LabError) as cm:
            lab.write_mode(self.conf, "always", run=run)
        msg = str(cm.exception)
        self.assertIn("systemctl disable erhai-gpu-pin-once.service", msg)
        self.assertIn("already rewritten", msg)
        self.assertEqual(lab.read_mode(self.conf.read_text()), "always")


class CmdMode(unittest.TestCase):
    def test_mode_needs_root(self):
        if os.geteuid() == 0:
            self.skipTest("running as root")
        with self.assertRaises(lab.LabError) as cm:
            lab.cmd_mode(lab.build_parser().parse_args(["mode", "always"]))
        self.assertIn("root", str(cm.exception))

    def test_parser_accepts_only_once_and_always(self):
        p = lab.build_parser()
        self.assertEqual(p.parse_args(["mode", "once"]).mode, "once")
        with self.assertRaises(SystemExit):
            p.parse_args(["mode", "off"])



class HelpText(unittest.TestCase):
    def test_docstring_lists_every_subcommand_in_parser_order(self):
        p = lab.build_parser()
        subs = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
        listed = re.findall(r"^  ([a-z][a-z0-9-]*)", lab.__doc__, re.MULTILINE)
        self.assertEqual(listed, list(subs.choices))
        self.assertIn("mode", listed)


if __name__ == "__main__":
    unittest.main()
