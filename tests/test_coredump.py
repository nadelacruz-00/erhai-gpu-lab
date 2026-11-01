# SPDX-License-Identifier: GPL-2.0-only
"""tablet/erhai-gpu-coredump against a fake devcoredump root in a tempdir."""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from labtool import REPO_ROOT

SCRIPT = REPO_ROOT / "tablet" / "erhai-gpu-coredump"
UNIT = REPO_ROOT / "tablet" / "erhai-gpu-coredump@.service"
RULES = REPO_ROOT / "tablet" / "70-erhai-gpu-coredump.rules"
BOOT = "01234567-89ab-cdef-0123-456789abcdef"
CONTENT = "ringbuffer:\ngmu-log:\n"


class Coredump(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tmp = Path(self._t.name)
        self.root = self.tmp / "devcd"
        self.store = self.tmp / "store"
        self.devs = self.tmp / "devs"
        self.root.mkdir()
        self.store.mkdir()
        (self.tmp / "boot_id").write_text(BOOT + "\n")
        self.add("devcd1", "3d00000.gpu")

    def add(self, name, dev):
        d = self.root / name
        d.mkdir()
        (d / "data").write_text(CONTENT)
        target = self.devs / dev
        target.mkdir(parents=True, exist_ok=True)
        (d / "failing_device").symlink_to(target)

    def run_script(self, name, **extra):
        env = dict(os.environ,
                   ERHAI_DEVCD_ROOT=str(self.root),
                   ERHAI_COREDUMP_DIR=str(self.store),
                   ERHAI_BOOT_ID_FILE=str(self.tmp / "boot_id"))
        env.update(extra)
        return subprocess.run(["bash", str(SCRIPT), name], env=env,
                              capture_output=True, text=True)

    def bins(self):
        return sorted(self.store.glob("*.bin"))

    def data(self, name="devcd1"):
        return (self.root / name / "data").read_text().strip()

    def test_gpu_dump_is_saved_then_freed(self):
        r = self.run_script("devcd1")
        self.assertEqual(r.returncode, 0, r.stderr)
        files = list(self.store.glob("01234567-*.bin"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_text(), CONTENT)
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.data(), "1")

    def test_copy_failure_still_frees(self):
        self.store.chmod(0o500)
        self.addCleanup(self.store.chmod, 0o700)
        r = self.run_script("devcd1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("erhai-gpu-coredump: copy failed", r.stderr)
        self.assertEqual(self.bins(), [])
        self.assertEqual(self.data(), "1")

    def test_rotation_keeps_newest_20(self):
        for i in range(1, 21):
            p = self.store / f"old-{i}.bin"
            p.write_text("x")
            os.utime(p, (i, i))
        r = self.run_script("devcd1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.bins()), 20)
        self.assertFalse((self.store / "old-1.bin").exists())
        self.assertTrue((self.store / "old-2.bin").exists())

    def test_bad_name_is_rejected(self):
        for name in ["../x", "devcdX", "devcd1/../y"]:
            r = self.run_script(name)
            self.assertEqual(r.returncode, 2, name)
        self.assertEqual(self.bins(), [])
        self.assertEqual(self.data(), CONTENT.strip())
        self.assertFalse((self.tmp / "x").exists())

    def test_non_gpu_devcd_is_untouched(self):
        self.add("devcd2", "ath12k_pci")
        r = self.run_script("devcd2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.bins(), [])
        self.assertEqual((self.root / "devcd2" / "data").read_text(), CONTENT)

    def test_missing_devcd_exits_quietly(self):
        r = self.run_script("devcd9")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.bins(), [])

    def test_same_second_names_do_not_collide(self):
        self.add("devcd2", "3d00000.gpu")
        for n in ("devcd1", "devcd2"):
            r = self.run_script(n, ERHAI_NOW="1793500000")
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([p.name for p in self.bins()],
                         ["01234567-1793500000-2.bin", "01234567-1793500000.bin"])

    def test_unit_is_udev_started_oneshot(self):
        unit = UNIT.read_text()
        self.assertIn("Type=oneshot", unit)
        self.assertIn("ExecStart=/usr/local/lib/erhai-gpu-lab/erhai-gpu-coredump %i", unit)
        self.assertNotIn("[Install]", unit)
        rules = RULES.read_text()
        for s in ['ACTION=="add"', 'SUBSYSTEM=="devcoredump"', 'KERNEL=="devcd[0-9]*"',
                  'ENV{SYSTEMD_WANTS}+="erhai-gpu-coredump@%k.service"']:
            self.assertIn(s, rules)


if __name__ == "__main__":
    unittest.main()
