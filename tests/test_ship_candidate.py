# SPDX-License-Identifier: GPL-2.0-only
"""tools/ship-candidate.sh: the refusal paths (all of which exit before any network use)."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from labtool import REPO_ROOT

SCRIPT = REPO_ROOT / "tools" / "ship-candidate.sh"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(cwd), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def make_lab(tmp: Path, remote: bool) -> Path:
    """A temp lab repo holding a copy of the script, one commit, optionally an origin."""
    lab = tmp / "lab"
    (lab / "tools").mkdir(parents=True)
    (lab / "tablet").mkdir()
    (lab / "candidates").mkdir()
    shutil.copy(SCRIPT, lab / "tools" / "ship-candidate.sh")
    (lab / "tablet" / "keep").write_text("x\n")
    git(lab, "init", "-q", "-b", "main")
    git(lab, "config", "user.name", "Fixture Author")
    git(lab, "config", "user.email", "fixture@example.invalid")
    git(lab, "add", "-A")
    git(lab, "commit", "-q", "-m", "init")
    if remote:
        bare = tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        git(lab, "remote", "add", "origin", str(bare))
    return lab


def run(lab: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(lab / "tools" / "ship-candidate.sh"), *args],
                          capture_output=True, text=True, timeout=60)


class ShipCandidateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_usage(self):
        lab = make_lab(self.tmp, remote=False)
        r = run(lab)
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr.lower())

    def test_usage_bad_option(self):
        lab = make_lab(self.tmp, remote=True)
        r = run(lab, "/k", "main", "cand", "--bogus")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr.lower())

    def test_refuses_without_remote(self):
        lab = make_lab(self.tmp, remote=False)
        r = run(lab, "/k", "main", "cand")
        self.assertEqual(r.returncode, 2)
        self.assertIn("no git remote; publish the lab repo first", r.stderr)

    def test_refuses_dirty_tree(self):
        lab = make_lab(self.tmp, remote=True)
        (lab / "tablet" / "stray").write_text("dirty\n")
        r = run(lab, "/k", "main", "cand")
        self.assertEqual(r.returncode, 2)
        self.assertIn("tablet/stray", r.stderr)

    def test_changes_inside_candidate_are_not_dirty(self):
        # Reaches the gh check, which fails or not depending on the host; either
        # way the dirty-tree refusal must not name the candidate's own files.
        lab = make_lab(self.tmp, remote=True)
        (lab / "candidates" / "cand").mkdir()
        (lab / "candidates" / "cand" / "x.patch").write_text("p\n")
        r = run(lab, "/nonexistent", "main", "cand")
        self.assertNotIn("candidates/cand", r.stderr)

    def test_syntax(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    def test_fetches_the_release_of_the_watched_run(self):
        # kernel.yml tags lab-<cand>-<run_number>; "latest" could be another run's build
        text = SCRIPT.read_text()
        self.assertIn('N=$(gh run view "$RUN" --json number -q .number)', text)
        self.assertIn('sudo erhai-gpu-lab fetch "$CAND" --tag "lab-$CAND-$N"', text)
        self.assertLess(text.index('gh run watch "$RUN"'), text.index("gh run view"))
        self.assertNotRegex(text, r'erhai-gpu-lab fetch "\$CAND" *\|')

    def test_no_trailers(self):
        self.assertNotIn("Co-Authored-By", SCRIPT.read_text())


if __name__ == "__main__":
    unittest.main()
