# SPDX-License-Identifier: GPL-2.0-only
"""tools/export-patches.sh: regenerate a candidate's patches from BASE_SHA..branch."""

import os
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
    ref = lab / "candidates" / "60-gpu-reference"
    ref.mkdir()
    (ref / "cmdline").write_text("console=tty0\n")
    (ref / "extra.config").write_text("CONFIG_SM_GPUCC_8750=y\n")
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

    def test_new_candidate_gets_reference_cmdline_and_config(self):
        r = self.run_export("work", "--prefix", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.cand / "cmdline").read_text(), "console=tty0\n")
        self.assertEqual((self.cand / "extra.config").read_text(), "CONFIG_SM_GPUCC_8750=y\n")

    def test_existing_cmdline_and_config_are_kept(self):
        self.cand.mkdir()
        (self.cand / "cmdline").write_text("own\n")
        (self.cand / "extra.config").write_text("CONFIG_OWN=y\n")
        self.assertEqual(self.run_export("work").returncode, 0)
        self.assertEqual((self.cand / "cmdline").read_text(), "own\n")
        self.assertEqual((self.cand / "extra.config").read_text(), "CONFIG_OWN=y\n")

    def test_missing_files_without_reference_dir_fails(self):
        shutil.rmtree(self.lab / "candidates" / "60-gpu-reference")
        r = self.run_export("work")
        self.assertEqual(r.returncode, 2)
        self.assertIn("60-gpu-reference", r.stderr)
        self.assertFalse(list(self.cand.glob("*.patch")) if self.cand.exists() else [])

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

    def test_patches_apply_with_p1_despite_noprefix(self):
        git(self.kernel, "config", "diff.noprefix", "true")
        git(self.kernel, "config", "diff.mnemonicPrefix", "true")
        r = self.run_export("work")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.cand / "0001-a.patch").read_text()
        self.assertIn("--- a/f", text)
        self.assertIn("+++ b/f", text)
        tree = Path(self._tmp.name) / "tree"
        tree.mkdir()
        (tree / "f").write_text("base\n")
        for p in sorted(self.cand.glob("*.patch")):
            subprocess.run(["patch", "-p1", "-i", str(p)], cwd=tree, check=True,
                           capture_output=True)
        self.assertEqual((tree / "f").read_text(), "c\n")

    def test_format_patch_failure_leaves_candidate_intact(self):
        self.assertEqual(self.run_export("work").returncode, 0)
        before = {p.name: p.read_text() for p in self.cand.iterdir()}
        shim = Path(self._tmp.name) / "shim"
        shim.mkdir()
        real = shutil.which("git")
        (shim / "git").write_text(
            '#!/bin/sh\nfor a in "$@"; do [ "$a" = format-patch ] && exit 1; done\n'
            f'exec {real} "$@"\n')
        (shim / "git").chmod(0o755)
        env = {**os.environ, "PATH": f"{shim}:{os.environ['PATH']}"}
        r = subprocess.run(
            ["bash", str(self.lab / "tools" / "export-patches.sh"),
             str(self.kernel), "work", "cand", "--prefix", "1"],
            capture_output=True, text=True, env=env)
        self.assertNotEqual(r.returncode, 0)
        after = {p.name: p.read_text() for p in self.cand.iterdir()}
        self.assertEqual(before, after)
        self.assertEqual([p.name for p in (self.lab / "candidates").iterdir()
                          if p.name.startswith(".export")], [])


if __name__ == "__main__":
    unittest.main()
