# SPDX-License-Identifier: GPL-2.0-only
"""tablet/install.sh, docs and .gitignore: static checks (install.sh needs root)."""

import unittest

from labtool import REPO_ROOT


class InstallSh(unittest.TestCase):
    def setUp(self):
        self.text = (REPO_ROOT / "tablet" / "install.sh").read_text()

    def test_installs_under_the_gpu_lab_names(self):
        self.assertIn("SBIN=/usr/local/sbin/erhai-gpu-lab\n", self.text)
        self.assertIn("/var/lib/erhai-gpu", self.text)
        self.assertIn('"$HERE/erhai-lab"', self.text)  # in-repo filename unchanged

    def test_install_copies_helpers(self):
        for needle in ["/usr/local/lib/erhai-gpu-lab", "gpu-checks.sh", "igt-recovery",
                       "setup.sh", "erhai-gpu-lab-boot.service",
                       "systemctl enable erhai-gpu-lab-boot.service"]:
            self.assertIn(needle, self.text)
        self.assertNotIn("enable erhai-gpu-lab-soak.timer", self.text)

    def test_no_charging_lab_paths_or_wording(self):
        self.assertNotIn("charging", self.text.lower())
        self.assertNotIn("/usr/local/sbin/erhai-lab\n", self.text)


class Docs(unittest.TestCase):
    def test_readme_and_ladder_use_installed_name(self):
        self.assertIn("erhai-gpu-lab fetch", (REPO_ROOT / "README.md").read_text())
        for doc in ["README.md", "docs/ladder.md"]:
            text = (REPO_ROOT / doc).read_text()
            self.assertNotRegex(text, r"(?<![-/\w])erhai-lab (fetch|whoami)", doc)

    def test_release_notes_use_installed_name(self):
        text = (REPO_ROOT / ".github" / "workflows" / "kernel.yml").read_text()
        self.assertIn("erhai-gpu-lab fetch", text)

    def test_ladder_g0_runs_with_sudo_and_names_pstore_next_boot(self):
        text = (REPO_ROOT / "docs" / "ladder.md").read_text()
        self.assertIn("`sudo tablet/gpu-checks.sh g0`", text)
        self.assertNotRegex(text, r"(?<!sudo )`tablet/gpu-checks\.sh g0")
        self.assertIn("NEXT boot", text)
        self.assertIn("/var/lib/systemd/pstore", text)

    def test_ladder_runbook(self):
        ladder = (REPO_ROOT / "docs" / "ladder.md").read_text()
        for needle in ["## Runbook", "erhai-gpu-lab soak start", "erhai-gpu-lab g1 --pinned",
                       "ship-candidate.sh", "picked by hand in rEFInd",
                       "sudo erhai-gpu-lab g1 --runs 1 --hangcheck 0"]:
            self.assertIn(needle, ladder)
        self.assertNotIn("shader loop", ladder)
        self.assertNotIn("efibootmgr", ladder)
        self.assertNotIn("(no root, once)", ladder)
        self.assertNotIn("igt-recovery/igt/", ladder)
        self.assertIn("erhai-gpu-lab report", (REPO_ROOT / "README.md").read_text())


class GitIgnore(unittest.TestCase):
    def test_superpowers_is_ignored(self):
        lines = (REPO_ROOT / ".gitignore").read_text().split()
        self.assertIn("/.superpowers/", lines)


if __name__ == "__main__":
    unittest.main()
