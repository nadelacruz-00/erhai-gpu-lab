# SPDX-License-Identifier: GPL-2.0-only
"""ci/build-candidate.sh guards and UKI cmdline (no kernel build: PRINT_CMDLINE=1)."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from labtool import REPO_ROOT

SCRIPT = REPO_ROOT / "ci" / "build-candidate.sh"
STACK = "0123456789abcdef0123456789abcdef01234567"


class BuildCandidate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.lab = Path(self._tmp.name) / "lab"
        (self.lab / "ci").mkdir(parents=True)
        shutil.copy(SCRIPT, self.lab / "ci" / "build-candidate.sh")
        (self.lab / "candidates").mkdir()
        (self.lab / "candidates" / "BASE_SHA").write_text("f" * 40 + "\n")
        self.cdir = self.lab / "candidates" / "cand"
        self.cdir.mkdir()
        (self.cdir / "cmdline").write_text("console=tty0\n  quiet\n")

    def run_build(self, **env):
        # KERNEL_REPO points nowhere: any attempt to fetch fails loudly.
        e = {"PATH": os.environ["PATH"], "KERNEL_REPO": "/nonexistent/repo",
             "WORK": str(self.lab / "work"), **env}
        return subprocess.run(["bash", str(self.lab / "ci" / "build-candidate.sh"), "cand", "42"],
                              env=e, capture_output=True, text=True)

    def test_stack_without_patches_fails_before_fetch(self):
        (self.cdir / "STACK").write_text(STACK + "\n")
        r = self.run_build()
        self.assertEqual(r.returncode, 1)
        self.assertIn("STACK present but no patches", r.stderr)
        self.assertNotIn("fetching", r.stdout)
        self.assertFalse((self.lab / "work").exists())

    def test_cmdline_carries_stack_sha12(self):
        (self.cdir / "STACK").write_text(STACK + "\n")
        (self.cdir / "0001-x.patch").write_text("x\n")
        r = self.run_build(PRINT_CMDLINE="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(),
                         "console=tty0 quiet erhai_lab.candidate=cand erhai_lab.build=42 "
                         f"erhai_lab.stack={STACK[:12]}")

    def test_cmdline_without_stack_has_no_stack_param(self):
        r = self.run_build(PRINT_CMDLINE="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(),
                         "console=tty0 quiet erhai_lab.candidate=cand erhai_lab.build=42")


if __name__ == "__main__":
    unittest.main()
