# SPDX-License-Identifier: GPL-2.0-only
"""erhai-gpu-lab boot log, reset classification and the queued g0 rung."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from labtool import REPO_ROOT, lab

JOURNAL = REPO_ROOT / "tests" / "fixtures" / "journal"


def fx(name):
    return (JOURNAL / name).read_text()


def ident(cand="package", **kw):
    d = {"boot_id": "0123456789abcdef0123456789abcdef", "kver": "7.3.0-test",
         "cand": cand, "build": "-", "stack": "-", "mode": "once"}
    d.update(kw)
    return d


class Classify(unittest.TestCase):
    def test_classify_clean(self):
        self.assertEqual(lab.classify_prev_boot(fx("prev-clean.txt"), fx("cur-normal.txt")),
                         "clean")

    def test_classify_clean_wins_over_1970(self):
        # a clean shutdown followed by a clock that restarted at 1970 is still clean
        self.assertEqual(lab.classify_prev_boot(fx("prev-clean.txt"), fx("cur-rtc-1970.txt")),
                         "clean")

    def test_classify_cold_rtc_1970(self):
        self.assertEqual(lab.classify_prev_boot(fx("prev-unclean.txt"), fx("cur-rtc-1970.txt")),
                         "cold")

    def test_classify_warm(self):
        self.assertEqual(lab.classify_prev_boot(fx("prev-unclean.txt"), fx("cur-normal.txt")),
                         "warm")

    def test_classify_no_previous_boot(self):
        self.assertEqual(lab.classify_prev_boot(None, fx("cur-normal.txt")), "none")


class BootRun(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.state = Path(self._td.name)
        self.calls = []

    def fake_g0(self, out):
        self.calls.append(out)
        with open(out, "a") as f:
            f.write("PASS probe\nFAIL zap\n")

    def queue(self, label="g0", expect="package"):
        (self.state / "queue.json").write_text(json.dumps({"label": label, "expect": expect}))

    def run_boot(self, **kw):
        args = dict(ident=ident(), prev_tail=fx("prev-clean.txt"),
                    cur_journal=fx("cur-normal.txt"), pstore_n=0, run_g0=self.fake_g0)
        args.update(kw)
        return lab.boot_run(self.state, **args)

    def test_boot_run_without_queue_only_logs(self):
        self.assertEqual(self.run_boot(), "logged")
        self.assertEqual(self.calls, [])
        lines = (self.state / "boots.log").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        rec = lab.parse_boots(lines[0])[0]
        self.assertEqual(rec["boot"], ident()["boot_id"])
        self.assertEqual(rec["kver"], "7.3.0-test")
        self.assertEqual(rec["cand"], "package")
        self.assertEqual(rec["mode"], "once")
        self.assertEqual(rec["prev"], "clean")
        self.assertEqual(rec["pstore"], "0")

    def test_boot_run_logs_reset_kind_and_pstore(self):
        self.run_boot(prev_tail=fx("prev-unclean.txt"), cur_journal=fx("cur-normal.txt"),
                      pstore_n=2)
        rec = lab.parse_boots((self.state / "boots.log").read_text())[0]
        self.assertEqual((rec["prev"], rec["pstore"]), ("warm", "2"))

    def test_boot_run_runs_and_consumes_queue(self):
        self.queue(expect="60-gpu-reference")
        out = self.run_boot(ident=ident(cand="60-gpu-reference", build="43", stack="x"))
        path = self.state / "g0-7.3.0-test-01234567.txt"
        self.assertEqual(self.calls, [path])
        self.assertIn("FAIL", out)
        self.assertIn(str(path), out)
        text = path.read_text().splitlines()
        self.assertEqual(text[0], "# kver=7.3.0-test cand=60-gpu-reference build=43 "
                                  "stack=x mode=once prev=clean")
        self.assertEqual(text[1:], ["PASS probe", "FAIL zap"])
        self.assertFalse((self.state / "queue.json").exists())
        self.assertEqual(len((self.state / "boots.log").read_text().splitlines()), 1)

    def test_boot_run_pass_verdict(self):
        self.queue()

        def ok(out):
            with open(out, "a") as f:
                f.write("PASS a\nINFO b FAIL not at start\n")
        self.assertTrue(self.run_boot(run_g0=ok).endswith("(PASS)"))

    def test_boot_run_keeps_queue_on_wrong_kernel(self):
        self.queue(expect="60-gpu-reference")
        out = self.run_boot()
        self.assertEqual(out, "queued g0 expects 60-gpu-reference, booted package; kept")
        self.assertTrue((self.state / "queue.json").exists())
        self.assertEqual(self.calls, [])
        self.assertEqual(len((self.state / "boots.log").read_text().splitlines()), 1)

    def test_boot_run_appends_across_boots(self):
        self.run_boot()
        self.run_boot(ident=ident(boot_id="f" * 32))
        self.assertEqual(len(lab.parse_boots((self.state / "boots.log").read_text())), 2)

    def test_boot_run_unreadable_queue_still_logs(self):
        (self.state / "queue.json").write_text("{not json")
        with self.assertRaises(lab.LabError):
            self.run_boot()
        self.assertEqual(len((self.state / "boots.log").read_text().splitlines()), 1)


class Queue(unittest.TestCase):
    def test_queue_package_matches_only_package(self):
        self.assertTrue(lab.queue_matches("package", "package"))
        self.assertFalse(lab.queue_matches("package", "60-gpu-reference"))
        self.assertFalse(lab.queue_matches("60-gpu-reference", "package"))
        self.assertTrue(lab.queue_matches("60-gpu-reference", "60-gpu-reference"))

    def test_queue_rejects_g1(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(lab.LabError, "only g0 runs at boot"):
                lab.write_queue(Path(td), "g1", "package")
            self.assertFalse((Path(td) / "queue.json").exists())

    def test_queue_rejects_bad_label(self):
        with tempfile.TemporaryDirectory() as td:
            for bad in ("", "x0", "g", "G0", "g0 x", "g0/../x"):
                with self.assertRaises(lab.LabError, msg=bad):
                    lab.write_queue(Path(td), bad, "package")

    def test_queue_writes_json(self):
        with tempfile.TemporaryDirectory() as td:
            lab.write_queue(Path(td), "g0", "60-gpu-reference")
            self.assertEqual(json.loads((Path(td) / "queue.json").read_text()),
                             {"label": "g0", "expect": "60-gpu-reference"})

    def test_queue_rejects_empty_expect(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(lab.LabError):
                lab.write_queue(Path(td), "g0", "")


class ParseBoots(unittest.TestCase):
    def test_parse_boots_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)
            lab.boot_run(state, ident(), fx("prev-unclean.txt"), fx("cur-rtc-1970.txt"), 1,
                         lambda p: None)
            recs = lab.parse_boots((state / "boots.log").read_text())
        self.assertEqual(recs, [{"boot": ident()["boot_id"], "kver": "7.3.0-test",
                                 "cand": "package", "build": "-", "mode": "once",
                                 "prev": "cold", "pstore": "1"}])

    def test_parse_boots_skips_blank_lines(self):
        self.assertEqual(lab.parse_boots("\n a=1 b=2 \n\n"), [{"a": "1", "b": "2"}])


class Status(unittest.TestCase):
    def test_status_report(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)
            lab.boot_run(state, ident(), None, fx("cur-normal.txt"), 0, lambda p: None)
            (state / "g0-a.txt").write_text("# hdr\nPASS a\nFAIL b\nFAIL c\nINFO d\n")
            (state / "power-x.txt").write_text("PASS only\n")
            (state / "notes.txt").write_text("PASS ignored\n")
            text = lab.status_report(state, "7.3.0-test: package kernel (not a lab build)",
                                     "once")
        self.assertIn("7.3.0-test: package kernel", text)
        self.assertIn("MODE=once", text)
        self.assertRegex(text, r"queue: none")
        self.assertIn("prev=none", text)
        self.assertRegex(text, r"g0-a\.txt\s+PASS=1 FAIL=2")
        self.assertRegex(text, r"power-x\.txt\s+PASS=1 FAIL=0")
        self.assertNotIn("notes.txt", text)

    def test_status_empty_state(self):
        with tempfile.TemporaryDirectory() as td:
            text = lab.status_report(Path(td) / "missing", "w", "?")
        self.assertIn("queue: none", text)
        self.assertIn("no boots logged", text)

    def test_status_shows_queue_and_limits_to_five(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)
            (state / "queue.json").write_text(json.dumps({"label": "g0", "expect": "package"}))
            for i in range(7):
                (state / f"g0-{i}.txt").write_text("PASS x\n")
                import os
                os.utime(state / f"g0-{i}.txt", (1000 + i, 1000 + i))
            text = lab.status_report(state, "w", "once")
        self.assertIn("queue: g0 expects package", text)
        self.assertEqual(len(re.findall(r"g0-\d\.txt", text)), 5)
        self.assertIn("g0-6.txt", text)
        self.assertNotIn("g0-1.txt", text)


class UnitFile(unittest.TestCase):
    def test_unit_file(self):
        text = (REPO_ROOT / "tablet" / "erhai-gpu-lab-boot.service").read_text()
        lines = text.splitlines()
        for want in ("Type=oneshot",
                     "After=graphical.target erhai-gpu-pin-once.service time-sync.target",
                     "WantedBy=graphical.target",
                     "ExecStart=/usr/local/sbin/erhai-gpu-lab boot-run",
                     "TimeoutStartSec=600"):
            self.assertIn(want, lines)


if __name__ == "__main__":
    unittest.main()
