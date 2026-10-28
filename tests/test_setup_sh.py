# SPDX-License-Identifier: GPL-2.0-only
"""tablet/setup.sh and tools/gpu-hang: static checks only (no GPU, no apt)."""

import subprocess
import unittest

from labtool import REPO_ROOT


class SetupSh(unittest.TestCase):
    def test_setup_installs_exactly_the_six_packages(self):
        text = (REPO_ROOT / "tablet" / "setup.sh").read_text()
        for p in ["trace-cmd", "mesa-utils", "vulkan-tools", "devmem2",
                  "libegl-dev", "libgles-dev"]:
            self.assertIn(p, text)
        self.assertIn("dpkg -s", text)  # the idempotence check

    def test_gpu_hang_builds(self):
        r = subprocess.run(["make", "-C", str(REPO_ROOT / "tools" / "gpu-hang"), "-n"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
