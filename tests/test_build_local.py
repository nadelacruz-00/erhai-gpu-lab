# SPDX-License-Identifier: GPL-2.0-only
"""tools/build-local.sh: argument checks, progress/summary and the time log, with a fake build."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from labtool import REPO_ROOT

SCRIPT = REPO_ROOT / "tools" / "build-local.sh"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(cwd), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


class BuildLocal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.kernel = tmp / "kernel"
        self.kernel.mkdir()
        git(self.kernel, "init", "-q")
        git(self.kernel, "config", "user.name", "Fixture Author")
        git(self.kernel, "config", "user.email", "fixture@example.invalid")
        (self.kernel / "f").write_text("x\n")
        git(self.kernel, "add", "-A")
        git(self.kernel, "commit", "-q", "-m", "base")
        self.lab = tmp / "lab"
        (self.lab / "tools").mkdir(parents=True)
        (self.lab / "candidates" / "cand").mkdir(parents=True)
        (self.lab / "candidates" / "BASE_SHA").write_text(git(self.kernel, "rev-parse", "HEAD") + "\n")
        shutil.copy(SCRIPT, self.lab / "tools" / "build-local.sh")
        self.fake = tmp / "fake-build"
        self.ci_gcc = ""          # default gcc unless a test opts in
        self.extra_env = {}

    def tearDown(self):
        self._tmp.cleanup()

    def fake_build(self, body: str):
        self.fake.write_text("#!/bin/bash\n" + body)
        self.fake.chmod(0o755)

    def run_script(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.lab / "tools" / "build-local.sh"), *args],
            capture_output=True, text=True, timeout=60,
            env={"PATH": "/usr/bin:/bin", "HOME": self._tmp.name, "BUILD_CMD": str(self.fake),
                 "CI_GCC": self.ci_gcc, **self.extra_env})

    def test_usage(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr)

    def test_unknown_candidate(self):
        self.fake_build("exit 0\n")
        r = self.run_script("nope", "--kernel-dir", str(self.kernel))
        self.assertEqual(r.returncode, 2)
        self.assertIn("no candidate dir", r.stderr)

    def test_kernel_dir_without_base_sha(self):
        self.fake_build("exit 0\n")
        (self.lab / "candidates" / "BASE_SHA").write_text("0" * 40 + "\n")
        r = self.run_script("cand", "--kernel-dir", str(self.kernel))
        self.assertEqual(r.returncode, 2)
        self.assertIn("does not have candidates/BASE_SHA", r.stderr)

    def test_candidate_base_is_checked_in_the_kernel_dir(self):
        self.fake_build("exit 0\n")
        (self.lab / "candidates" / "cand" / "BASE_SHA").write_text("0" * 40 + "\n")
        r = self.run_script("cand", "--kernel-dir", str(self.kernel))
        self.assertEqual(r.returncode, 2)
        self.assertIn("does not have candidates/cand/BASE_SHA", r.stderr)

    def test_success_records_time_and_object_count(self):
        self.fake_build('[ "$KERNEL_REPO" = "%s" ] || exit 9\n'
                        'echo "fetching x"; for i in 1 2 3; do echo "  CC      a$i.o"; done\n'
                        'echo "  CC [M]  m.o"; echo "kernelrelease: 7.3-lab-cand"\n' % self.kernel)
        r = self.run_script("cand", "--kernel-dir", str(self.kernel), "--interval", "0.2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("cand built in", r.stdout)
        self.assertIn("4 objects", r.stdout)
        self.assertIn(f"--from-dir {self.lab}/out/cand", r.stdout)
        state = self.lab / "out" / ".build-local"
        self.assertEqual((state / "cand.objects").read_text().strip(), "4")
        times = (state / "times.log").read_text()
        self.assertRegex(times, r"cand=cand rc=0 elapsed=\d+s objects=4 peakC=")

    def test_incremental_build_keeps_full_count(self):
        state = self.lab / "out" / ".build-local"
        state.mkdir(parents=True)
        (state / "cand.objects").write_text("100\n")
        self.fake_build('echo "  CC      one.o"\n')
        r = self.run_script("cand", "--kernel-dir", str(self.kernel), "--interval", "0.2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((state / "cand.objects").read_text().strip(), "100")

    def test_ci_gcc_missing_refuses(self):
        self.fake_build("exit 0\n")
        self.ci_gcc = "99"
        r = self.run_script("cand", "--kernel-dir", str(self.kernel))
        self.assertEqual(r.returncode, 2)
        self.assertIn("gcc-99 not installed", r.stderr)

    def test_ci_gcc_sets_cross_compile_prefix(self):
        bindir = Path(self._tmp.name) / "bin"
        bindir.mkdir()
        (bindir / "gcc-77").write_text("#!/bin/sh\necho fake\n")
        (bindir / "gcc-77").chmod(0o755)
        self.ci_gcc = "77"
        self.extra_env = {"PATH": f"{bindir}:/usr/bin:/bin"}
        self.fake_build('echo "XC=$CROSS_COMPILE"; readlink "${CROSS_COMPILE}gcc"; echo "  CC      a.o"\n')
        r = self.run_script("cand", "--kernel-dir", str(self.kernel), "--interval", "0.2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        log = (self.lab / "out" / ".build-local" / "cand.log").read_text()
        self.assertIn("toolchain-gcc77/", log)
        self.assertIn(str(bindir / "gcc-77"), log)

    def test_failure_propagates_and_shows_log(self):
        self.fake_build('echo "  CC      a.o"; echo "error: boom" >&2; exit 3\n')
        r = self.run_script("cand", "--kernel-dir", str(self.kernel), "--interval", "0.2")
        self.assertEqual(r.returncode, 3)
        self.assertIn("FAILED rc=3", r.stdout)
        self.assertIn("error: boom", r.stdout)
        self.assertIn("rc=3", (self.lab / "out" / ".build-local" / "times.log").read_text())


if __name__ == "__main__":
    unittest.main()
