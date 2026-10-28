# SPDX-License-Identifier: GPL-2.0-only
"""erhai-gpu-lab boot log, reset classification and the queued g0 rung."""

import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


    def test_boot_run_consumes_queue_before_g0_even_if_it_raises(self):
        self.queue()

        def boom(out):
            raise lab.LabError("g0 died")
        with self.assertRaises(lab.LabError):
            self.run_boot(run_g0=boom)
        self.assertFalse((self.state / "queue.json").exists())
        ev = self.state / "g0-7.3.0-test-01234567.txt"
        self.assertTrue(ev.read_text().startswith("# kver=7.3.0-test cand=package"))
        self.assertEqual(len((self.state / "boots.log").read_text().splitlines()), 1)

    def test_boot_run_missing_helper_keeps_queue_and_writes_no_evidence(self):
        self.queue()

        def missing():
            raise lab.LabError("gpu-checks.sh not installed")
        with self.assertRaises(lab.LabError):
            self.run_boot(preflight=missing)
        self.assertTrue((self.state / "queue.json").exists())
        self.assertEqual(self.calls, [])
        self.assertEqual(list(self.state.glob("g0-*.txt")), [])
        self.assertEqual(len((self.state / "boots.log").read_text().splitlines()), 1)

    def test_boot_run_preflight_not_called_without_a_run(self):
        def never():
            raise AssertionError("preflight called")
        self.assertEqual(self.run_boot(preflight=never), "logged")

    def test_boot_run_unlogged_writes_prev_unknown(self):
        # an unclean journal tail is ignored: the boot before this one is unknown
        self.run_boot(prev_tail=fx("prev-unclean.txt"), pstore_n=1,
                      unlogged=["1" * 32, "2" * 32])
        line = (self.state / "boots.log").read_text()
        self.assertTrue(line.endswith(" prev=unknown pstore=1 "
                                      "unlogged=11111111,22222222\n"), line)
        rec = lab.parse_boots(line)[0]
        self.assertEqual(list(rec), ["boot", "kver", "cand", "build", "mode", "prev",
                                     "pstore", "unlogged"])

    def test_boot_run_unlogged_g0_header(self):
        self.queue()
        self.run_boot(unlogged=["1" * 32])
        ev = self.state / "g0-7.3.0-test-01234567.txt"
        self.assertTrue(ev.read_text().splitlines()[0].endswith(" prev=unknown"))

    def test_boot_run_no_unlogged_key_without_unlogged_boots(self):
        self.run_boot(unlogged=[])
        self.assertNotIn("unlogged", (self.state / "boots.log").read_text())


def listing(*pairs):
    """journalctl --list-boots -o json entries from (index, boot_id) pairs."""
    return [{"index": i, "boot_id": b, "first_entry": 1, "last_entry": 2} for i, b in pairs]


OLD, A, X, Y, C = ("0" * 32, "a" * 32, "e" * 32, "f" * 32, "c" * 32)


class UnloggedBoots(unittest.TestCase):
    def logged(self, *ids):
        return [{"boot": b, "prev": "clean"} for b in ids]

    def test_unlogged_boot_between_last_logged_and_this_boot(self):
        # OLD predates the lab (never logged): only boots after the last logged count
        lst = listing((-3, OLD), (-2, A), (-1, X), (0, C))
        self.assertEqual(lab.unlogged_boots(lst, self.logged(A), C), [X])

    def test_none_when_last_logged_is_the_previous_boot(self):
        lst = listing((-2, OLD), (-1, A), (0, C))
        self.assertEqual(lab.unlogged_boots(lst, self.logged(A), C), [])

    def test_empty_boots_log_is_no_guess(self):
        lst = listing((-2, OLD), (-1, A), (0, C))
        self.assertEqual(lab.unlogged_boots(lst, [], C), [])

    def test_last_logged_missing_from_listing_is_no_guess(self):
        lst = listing((-2, OLD), (-1, X), (0, C))
        self.assertEqual(lab.unlogged_boots(lst, self.logged(A), C), [])

    def test_index_order_and_exclusions(self):
        # unsorted listing; Y logged earlier is not unlogged; this boot is excluded
        lst = listing((0, C), (-1, X), (-4, A), (-2, Y), (-3, OLD))
        self.assertEqual(lab.unlogged_boots(lst, self.logged(Y, A), C), [OLD, X])

    def test_this_boot_already_logged(self):
        # boot-run run twice in one boot: the last line is this boot, index 0
        lst = listing((-1, A), (0, C))
        self.assertEqual(lab.unlogged_boots(lst, self.logged(A, C), C), [])

    def test_malformed_entries_are_skipped(self):
        lst = [None, {"index": "x", "boot_id": X}, {"boot_id": Y}, *listing((-1, A), (0, C))]
        self.assertEqual(lab.unlogged_boots(lst, self.logged(A), C), [])


class CmdBootRun(unittest.TestCase):
    """cmd_boot_run with the journal, boot id, cmdline and state patched."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.state = self.dir / "state"
        self.state.mkdir()
        (self.dir / "boot_id").write_text("cccccccc-cccc-cccc-cccc-cccccccccccc\n")
        (self.dir / "cmdline").write_text("quiet\n")
        (self.dir / "gpu-pin.conf").write_text("MODE=once\n")
        self.journal_calls = []
        for p in (mock.patch.object(lab, "STATE_DIR", self.state),
                  mock.patch.object(lab, "BOOT_ID_PATH", self.dir / "boot_id"),
                  mock.patch.object(lab, "PROC_CMDLINE", self.dir / "cmdline"),
                  mock.patch.object(lab, "PIN_CONF", self.dir / "gpu-pin.conf"),
                  mock.patch.object(lab, "PSTORE_DIR", self.dir / "no-pstore"),
                  mock.patch.object(lab, "require_root"),
                  mock.patch.object(lab, "_journal", side_effect=self.journal),
                  mock.patch.object(lab.os, "uname",
                                    return_value=mock.Mock(release="7.3.0-test"))):
            p.start()
            self.addCleanup(p.stop)

    def journal(self, *args):
        self.journal_calls.append(args)
        if args[:2] == ("-b", A):
            return fx("prev-clean.txt")
        if args[:2] == ("-b", "-1"):
            return fx("prev-unclean.txt")
        return fx("cur-normal.txt")

    def run_cmd(self, list_boots):
        with mock.patch.object(lab.subprocess, "run", side_effect=list_boots) as run, \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()) as err:
            rc = lab.cmd_boot_run(None)
        self.assertEqual(rc, 0, err.getvalue())
        for call in run.call_args_list:
            self.assertEqual(call.args[0],
                             ["journalctl", "--list-boots", "-o", "json", "--no-pager"])
        return lab.parse_boots((self.state / "boots.log").read_text())[-1]

    def listed(self, *pairs):
        out = json.dumps(listing(*pairs))
        return lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, out, "")

    def test_cmd_boot_run_names_unlogged_boot_instead_of_guessing(self):
        # A ended cleanly, X froze before boot-run could log it, C is this boot
        (self.state / "boots.log").write_text(f"boot={A} prev=none pstore=0\n")
        rec = self.run_cmd(self.listed((-3, OLD), (-2, A), (-1, X), (0, C)))
        self.assertEqual(rec["boot"], C)
        self.assertEqual((rec["prev"], rec["unlogged"]), ("unknown", "eeeeeeee"))
        self.assertFalse(any(a[:1] == ("-b",) and len(a) > 2 for a in self.journal_calls),
                         self.journal_calls)

    def test_cmd_boot_run_previous_boot_logged_uses_its_journal(self):
        (self.state / "boots.log").write_text(f"boot={A} prev=none pstore=0\n")
        rec = self.run_cmd(self.listed((-2, OLD), (-1, A), (0, C)))
        self.assertEqual(rec["prev"], "clean")
        self.assertNotIn("unlogged", rec)
        self.assertIn(("-b", A, "-n", "20"), self.journal_calls)

    def test_cmd_boot_run_list_boots_failure_keeps_old_behaviour(self):
        for result in (lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, "", "x"),
                       lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "not json", ""),
                       lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, "{}", ""),
                       OSError("no journalctl")):
            (self.state / "boots.log").write_text(f"boot={A} prev=none pstore=0\n")
            rec = self.run_cmd(result)
            self.assertEqual(rec["prev"], "clean")
            self.assertNotIn("unlogged", rec)


class PrevBootId(unittest.TestCase):
    def test_prev_boot_id_last_line(self):
        text = "boot=aaa kver=x\nboot=bbb kver=x\n"
        self.assertEqual(lab.prev_boot_id(text, "ccc"), "bbb")

    def test_prev_boot_id_empty_log(self):
        self.assertIsNone(lab.prev_boot_id("", "ccc"))
        self.assertIsNone(lab.prev_boot_id("\n\n", "ccc"))

    def test_prev_boot_id_last_is_this_boot(self):
        self.assertIsNone(lab.prev_boot_id("boot=aaa kver=x\nboot=ccc kver=x\n", "ccc"))


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
                os.utime(state / f"g0-{i}.txt", (1000 + i, 1000 + i))
            text = lab.status_report(state, "w", "once")
        self.assertIn("queue: g0 expects package", text)
        self.assertEqual(len(re.findall(r"g0-\d\.txt", text)), 5)
        self.assertIn("g0-6.txt", text)
        self.assertNotIn("g0-1.txt", text)


class ThisBootId(unittest.TestCase):
    def test_this_boot_id_is_dashless(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "boot_id"
            p.write_text("01234567-89ab-cdef-0123-456789abcdef\n")
            with mock.patch.object(lab, "BOOT_ID_PATH", p):
                self.assertEqual(lab.this_boot_id(), "0123456789abcdef0123456789abcdef")

    def test_this_boot_id_unreadable_is_lab_error(self):
        with mock.patch.object(lab, "BOOT_ID_PATH", Path("/nonexistent/boot_id")):
            with self.assertRaisesRegex(lab.LabError, "cannot read /nonexistent/boot_id"):
                lab.this_boot_id()

    def test_single_boot_id_path(self):
        self.assertFalse(hasattr(lab, "PROC_BOOT_ID"))
        self.assertFalse(hasattr(lab, "_this_boot_id"))
        src = (REPO_ROOT / "tablet" / "erhai-lab").read_text()
        self.assertEqual(src.count("BOOT_ID_PATH.read_text"), 1)


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
