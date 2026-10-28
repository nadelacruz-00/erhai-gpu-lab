# SPDX-License-Identifier: GPL-2.0-only
"""fetch: SHA256SUMS and asset verification."""

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from labtool import lab

KVER = "7.3.0-rc5-sm8750-themojoman-lab-00-cp-trace"


def write_release(d: Path, kver: str = KVER, sums: bool = True,
                  corrupt: str | None = None) -> None:
    files = {
        f"{kver}.efi": b"uki",
        f"modules-{kver}.tar.zst": b"modules",
        f"config-{kver}": b"CONFIG_FTRACE=y\n",
    }
    for name, data in files.items():
        (d / name).write_bytes(data)
    if sums:
        lines = [f"{hashlib.sha256(data).hexdigest()}  {name}"
                 for name, data in files.items()]
        (d / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    if corrupt:
        (d / corrupt).write_bytes(b"tampered")


class VerifyAssets(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_intact_release_verifies_and_identifies(self):
        write_release(self.d)
        lab.verify_assets(self.d)
        a = lab.identify_assets(self.d, "00-cp-trace")
        self.assertEqual(a.kver, KVER)
        self.assertEqual(a.uki.name, f"{KVER}.efi")

    def test_missing_sums_refuses(self):
        write_release(self.d, sums=False)
        with self.assertRaisesRegex(lab.LabError, "no SHA256SUMS"):
            lab.verify_assets(self.d)

    def test_checksum_mismatch_refuses(self):
        write_release(self.d, corrupt=f"{KVER}.efi")
        with self.assertRaisesRegex(lab.LabError, "checksum mismatch"):
            lab.verify_assets(self.d)

    def test_unlisted_file_refuses(self):
        write_release(self.d)
        (self.d / "extra.bin").write_bytes(b"x")
        with self.assertRaisesRegex(lab.LabError, "not listed"):
            lab.verify_assets(self.d)

    def test_listed_but_missing_refuses(self):
        write_release(self.d)
        (self.d / f"config-{KVER}").unlink()
        with self.assertRaisesRegex(lab.LabError, "not downloaded"):
            lab.verify_assets(self.d)

    def test_uki_modules_kver_mismatch_refuses(self):
        write_release(self.d)
        (self.d / f"modules-{KVER}.tar.zst").rename(
            self.d / "modules-7.3.0-rc5-sm8750-themojoman-lab-10-pd9v.tar.zst")
        with self.assertRaisesRegex(lab.LabError, "does not match"):
            lab.identify_assets(self.d, "00-cp-trace")

    def test_wrong_candidate_refuses(self):
        write_release(self.d)
        with self.assertRaisesRegex(lab.LabError, "not a lab build"):
            lab.identify_assets(self.d, "20-cp-current-ladder")

    def test_package_kernelrelease_is_never_installed(self):
        a = lab.Assets("7.3.0-rc5-sm8750-themojoman", self.d / "a.efi",
                       self.d / "m.tar.zst", self.d / "c")
        with self.assertRaisesRegex(lab.LabError, "non-lab"):
            lab.install_assets(a, boot_dir=self.d, modules_dir=self.d)

    def test_malformed_sums_line_refuses(self):
        with self.assertRaisesRegex(lab.LabError, "malformed"):
            lab.parse_sums("not a checksum line\n")


class ReleaseAssets(unittest.TestCase):
    def test_picks_the_tagged_release(self):
        releases = [
            {"tag_name": "lab-00-cp-trace-1", "assets": [{"name": "a", "browser_download_url": "u1"}]},
            {"tag_name": "lab-00-cp-trace-2", "assets": [
                {"name": "x.efi", "browser_download_url": "u2"},
                {"name": "SHA256SUMS", "browser_download_url": "u3"}]},
        ]
        self.assertEqual(lab.release_assets(releases, "lab-00-cp-trace-2"),
                         [("x.efi", "u2"), ("SHA256SUMS", "u3")])

    def test_missing_release_refuses(self):
        with self.assertRaisesRegex(lab.LabError, "not found"):
            lab.release_assets([], "lab-00-cp-trace-9")


class FindRelease(unittest.TestCase):
    TAGGED = {"tag_name": "lab-30-pr-final-7",
              "assets": [{"name": "SHA256SUMS", "browser_download_url": "u"}]}

    def fake_get(self, listing):
        calls = []

        def get(url):
            calls.append(url)
            if url.endswith("/releases?per_page=100"):
                return json.dumps(listing).encode()
            if url.endswith("/releases/tags/lab-30-pr-final-7"):
                return json.dumps(self.TAGGED).encode()
            raise lab.LabError(f"GET {url}: HTTP 404 Not Found")
        return get, calls

    def test_latest_from_the_list(self):
        get, calls = self.fake_get([self.TAGGED])
        tag, assets = lab.find_release("r", "30-pr-final", None, get)
        self.assertEqual(tag, "lab-30-pr-final-7")
        self.assertEqual(assets, [("SHA256SUMS", "u")])
        self.assertEqual(len(calls), 1)

    def test_empty_list_with_tag_falls_back_to_by_tag(self):
        get, calls = self.fake_get([])
        tag, assets = lab.find_release("r", "30-pr-final", "lab-30-pr-final-7", get)
        self.assertEqual(assets, [("SHA256SUMS", "u")])
        self.assertTrue(calls[-1].endswith("/releases/tags/lab-30-pr-final-7"))

    def test_empty_list_without_tag_asks_for_one(self):
        get, _ = self.fake_get([])
        with self.assertRaisesRegex(lab.LabError, "--tag"):
            lab.find_release("r", "30-pr-final", None, get)


class LatestTag(unittest.TestCase):
    def test_highest_run_for_candidate(self):
        tags = ["lab-00-cp-trace-3", "lab-00-cp-trace-12", "lab-20-cp-current-ladder-40",
                "lab-00-cp-trace-x", "v1"]
        self.assertEqual(lab.latest_tag(tags, "00-cp-trace"), "lab-00-cp-trace-12")

    def test_no_release_refuses(self):
        with self.assertRaisesRegex(lab.LabError, "no release"):
            lab.latest_tag(["lab-20-cp-current-ladder-1"], "00-cp-trace")


class RepoIdentity(unittest.TestCase):
    def test_repo_is_the_gpu_lab(self):
        self.assertEqual(lab.REPO, "nadelacruz-00/erhai-gpu-lab")


class Whoami(unittest.TestCase):
    def whoami(self, cmdline: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix="cmdline") as f:
            f.write(cmdline)
            f.flush()
            old, lab.PROC_CMDLINE = lab.PROC_CMDLINE, Path(f.name)
            try:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(lab.cmd_whoami(None), 0)
            finally:
                lab.PROC_CMDLINE = old
        return out.getvalue()

    def test_prints_stack_when_present(self):
        out = self.whoami("root=x erhai_lab.candidate=60-gpu-reference-p6 "
                          "erhai_lab.build=12 erhai_lab.stack=0123456789ab\n")
        self.assertIn("lab candidate 60-gpu-reference-p6, build 12", out)
        self.assertIn("stack=0123456789ab", out)

    def test_no_stack_param_prints_no_stack(self):
        out = self.whoami("root=x erhai_lab.candidate=60-gpu-reference erhai_lab.build=3\n")
        self.assertIn("lab candidate 60-gpu-reference, build 3", out)
        self.assertNotIn("stack=", out)


if __name__ == "__main__":
    unittest.main()


class FetchFromDir(unittest.TestCase):
    """fetch --from-dir: a local build gets the same checks as a release."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def run_fetch(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()) as err:
            rc = lab.main(["fetch", "00-cp-trace", "--from-dir", str(self.d), "--verify-only", *extra])
        return rc, out.getvalue(), err.getvalue()

    def test_verified_local_build(self):
        write_release(self.d)
        rc, out, _ = self.run_fetch()
        self.assertEqual(rc, 0)
        self.assertIn(f"local {self.d}: verified {KVER}", out)

    def test_tampered_local_build_refuses(self):
        write_release(self.d, corrupt=f"{KVER}.efi")
        rc, _, err = self.run_fetch()
        self.assertEqual(rc, 2)
        self.assertIn("checksum mismatch", err)

    def test_missing_dir_refuses(self):
        self.d = self.d / "nope"
        rc, _, err = self.run_fetch()
        self.assertEqual(rc, 2)
        self.assertIn("is not a directory", err)
