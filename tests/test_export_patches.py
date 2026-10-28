# SPDX-License-Identifier: GPL-2.0-only
"""tools/export-patches.sh: regenerate a candidate's patches from BASE_SHA..branch."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from labtool import REPO_ROOT

SCRIPT = REPO_ROOT / "tools" / "export-patches.sh"
GIT_ID = ["-c", "user.name=Fixture Author", "-c", "user.email=fixture@example.invalid",
          "-c", "commit.gpgsign=false"]


def git(kernel: Path, *args: str) -> str:
    return subprocess.run(["git", *GIT_ID, "-C", str(kernel), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def make_repo(tmp: Path):
    """Return (kernel_dir, base_sha, lab_root); lab_root is a temp copy of the layout."""
    kernel = tmp / "kernel"
    kernel.mkdir()
    git(kernel, "init", "-q", "-b", "main")
    (kernel / "f").write_text("base\n")
    git(kernel, "add", "f")
    git(kernel, "commit", "-q", "-m", "base")
    base = git(kernel, "rev-parse", "HEAD")
    lab = tmp / "lab"
    (lab / "candidates").mkdir(parents=True)
    (lab / "tools").mkdir()
    (lab / "candidates" / "BASE_SHA").write_text(base + "\n")
    shutil.copy(SCRIPT, lab / "tools" / "export-patches.sh")
    git(kernel, "checkout", "-q", "-b", "work")
    for name in "abc":
        (kernel / "f").write_text(f"{name}\n")
        git(kernel, "commit", "-q", "-a", "-m", name)
    git(kernel, "checkout", "-q", "--orphan", "orphan")
    git(kernel, "commit", "-q", "--allow-empty", "-m", "orphan")
    git(kernel, "checkout", "-q", "work")
    return kernel, base, lab


class ExportPatches(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.kernel, self.base, self.lab = make_repo(Path(self._tmp.name))
        self.cand = self.lab / "candidates" / "cand"

    def run_export(self, branch, *extra, kernel=None):
        return subprocess.run(
            ["bash", str(self.lab / "tools" / "export-patches.sh"),
             str(kernel or self.kernel), branch, "cand", *extra],
            capture_output=True, text=True)

    def test_exports_one_file_per_commit_and_stack(self):
        r = self.run_export("work")
        self.assertEqual(r.returncode, 0, r.stderr)
        files = sorted(p.name for p in self.cand.glob("*.patch"))
        self.assertEqual(len(files), 3)
        self.assertTrue(files[0].startswith("0001-"))
        self.assertEqual((self.cand / "STACK").read_text().strip(),
                         git(self.kernel, "rev-parse", "work"))
        self.assertEqual(len(r.stdout.strip().splitlines()), 3)

    def test_removes_stale_patch_files(self):
        self.cand.mkdir()
        (self.cand / "0009-stale.patch").write_text("stale")
        self.run_export("work")
        self.assertFalse((self.cand / "0009-stale.patch").exists())

    def test_prefix_keeps_first_n_commits(self):
        r = self.run_export("work", "--prefix", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(list(self.cand.glob("*.patch"))), 2)
        self.assertEqual((self.cand / "STACK").read_text().strip(),
                         git(self.kernel, "rev-parse", "work~1"))

    def test_branch_not_on_base_fails(self):
        r = self.run_export("orphan")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a descendant", r.stderr)

    def test_not_a_git_repo_fails(self):
        plain = Path(self._tmp.name) / "plain"
        plain.mkdir()
        r = self.run_export("work", kernel=plain)
        self.assertNotEqual(r.returncode, 0)

    def test_patches_carry_original_author(self):
        self.run_export("work")
        text = (self.cand / "0001-a.patch").read_text()
        self.assertIn("From: Fixture Author <fixture@example.invalid>", text)


if __name__ == "__main__":
    unittest.main()
