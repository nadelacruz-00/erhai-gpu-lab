# SPDX-License-Identifier: GPL-2.0-only
"""tablet/setup.sh and tools/igt-recovery: static checks only (no GPU, no apt, no root)."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from labtool import REPO_ROOT, lab

IGT = REPO_ROOT / "tools" / "igt-recovery" / "igt-recovery"


class SetupSh(unittest.TestCase):
    def test_setup_installs_the_tools_and_igt_build_deps(self):
        text = (REPO_ROOT / "tablet" / "setup.sh").read_text()
        for p in ["trace-cmd", "mesa-utils", "vulkan-tools", "meson",
                  "ninja-build", "libdrm-dev", "libkmod-dev", "libdw-dev",
                  "libpciaccess-dev", "libpci-dev", "libudev-dev"]:
            self.assertIn(p, text)
        # devmem2 reset the tablet reading the firewalled qfprom (2026-10-28)
        self.assertNotIn("devmem2", text)
        self.assertIn("dpkg -s", text)  # the idempotence check

    def test_igt_recovery_is_pinned(self):
        text = IGT.read_text()
        self.assertIn("IGT_TAG=v2.6", text)
        self.assertRegex(text, r"IGT_COMMIT=[0-9a-f]{40}\n")
        self.assertIn("tests/msm/msm_recovery", text)

    def test_igt_recovery_usage_and_subtests(self):
        for args, msg in [([], "usage"), (["run", "gpu-fault-parallel"], "unknown subtest")]:
            r = subprocess.run(["bash", str(IGT), *args], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn(msg, r.stderr)

    def test_igt_recovery_run_needs_root(self):
        if os.geteuid() == 0:
            self.skipTest("running as root")
        r = subprocess.run(["bash", str(IGT), "run"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs root", r.stderr)

    def test_igt_dir_defaults_to_state(self):
        self.assertIn("IGT_DIR=${IGT_DIR:-/var/lib/erhai-gpu/igt}\n", IGT.read_text())

    def test_igt_recovery_parses(self):
        r = subprocess.run(["bash", "-n", str(IGT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class Helper(unittest.TestCase):
    def test_helper_missing_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = lab.LIB_DIR
            lab.LIB_DIR = Path(tmp)
            try:
                with self.assertRaises(lab.LabError) as cm:
                    lab.helper("setup.sh")
                self.assertIn("not installed", str(cm.exception))
                (Path(tmp) / "setup.sh").write_text("")
                self.assertEqual(lab.helper("setup.sh"), Path(tmp) / "setup.sh")
            finally:
                lab.LIB_DIR = old


if __name__ == "__main__":
    unittest.main()
