# SPDX-License-Identifier: GPL-2.0-only
"""ci/assert-config.sh: a symbol dropped by olddefconfig fails the build."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from labtool import REPO_ROOT

SCRIPT = REPO_ROOT / "ci" / "assert-config.sh"
CANDIDATES = REPO_ROOT / "candidates"


def run(frag: str, config: str) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "extra.config"
        c = Path(tmp) / ".config"
        f.write_text(frag)
        c.write_text(config)
        return subprocess.run(["bash", str(SCRIPT), str(f), str(c)],
                              capture_output=True, text=True)


class AssertConfig(unittest.TestCase):
    def test_all_present(self):
        r = run("CONFIG_FTRACE=y\n# CONFIG_FOO is not set\n",
                "CONFIG_FTRACE=y\n# CONFIG_FOO is not set\nCONFIG_BAR=m\n")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_dropped_symbol_fails(self):
        r = run("CONFIG_TRACEPOINTS=y\n", "CONFIG_FTRACE=y\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CONFIG_TRACEPOINTS=y", r.stderr)

    def test_changed_value_fails(self):
        r = run("CONFIG_LOG_BUF_SHIFT=18\n", "CONFIG_LOG_BUF_SHIFT=17\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("got 'CONFIG_LOG_BUF_SHIFT=17'", r.stderr)

    def test_shipped_fragments_are_well_formed(self):
        frags = sorted(CANDIDATES.glob("*/extra.config"))
        self.assertTrue(frags, "no candidate ships an extra.config")
        for frag in frags:
            for line in frag.read_text().splitlines():
                with self.subTest(fragment=frag.parent.name, line=line):
                    self.assertRegex(line, r"^(CONFIG_[A-Z0-9_]+=.+|# CONFIG_[A-Z0-9_]+ is not set)$")

    def test_every_candidate_asserts_the_tracer(self):
        # Every rung's evidence is the erhai_pps tracepoint (eng review D3/D6);
        # a build without the tracer cannot produce its numbers.
        # erhai_defconfig only selects these indirectly.
        for d in sorted(p for p in CANDIDATES.iterdir() if p.is_dir()):
            frag = (d / "extra.config").read_text().splitlines()
            for sym in ("CONFIG_FTRACE=y", "CONFIG_TRACING=y", "CONFIG_TRACEPOINTS=y"):
                with self.subTest(candidate=d.name, symbol=sym):
                    self.assertIn(sym, frag)

    def test_candidate_60_fragment_is_asserted_verbatim(self):
        frag = (CANDIDATES / "60-gpu-reference" / "extra.config").read_text()
        self.assertIn("CONFIG_DPM_WATCHDOG_TIMEOUT=60\n", frag)
        self.assertIn("# CONFIG_RESET_SIMPLE is not set\n", frag)
        r = run(frag, frag)                       # a .config that matches the fragment exactly
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_dropped_dpm_watchdog_fails(self):
        frag = (CANDIDATES / "60-gpu-reference" / "extra.config").read_text()
        r = run(frag, frag.replace("CONFIG_DPM_WATCHDOG=y\n", "# CONFIG_DPM_WATCHDOG is not set\n"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("DPM_WATCHDOG", r.stderr)


class Candidates(unittest.TestCase):
    def test_base_sha_is_a_full_commit(self):
        self.assertRegex((CANDIDATES / "BASE_SHA").read_text().strip(), r"^[0-9a-f]{40}$")

    def test_every_candidate_has_a_cmdline(self):
        for d in sorted(p for p in CANDIDATES.iterdir() if p.is_dir()):
            with self.subTest(candidate=d.name):
                self.assertTrue((d / "cmdline").is_file())


if __name__ == "__main__":
    unittest.main()
