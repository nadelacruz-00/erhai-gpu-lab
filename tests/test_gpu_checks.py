# SPDX-License-Identifier: GPL-2.0-only
"""tablet/gpu-checks.sh against fake sysfs/dmesg fixture trees.

tests/fixtures/gpu-checks/pass is the full tree; every other fixture is an
overlay copied on top of it, plus an optional REMOVE file (paths to delete).
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from labtool import REPO_ROOT

SCRIPT = REPO_ROOT / "tablet" / "gpu-checks.sh"
FIX = REPO_ROOT / "tests" / "fixtures" / "gpu-checks"


def build(name, tmp):
    dst = Path(tmp) / name
    shutil.copytree(FIX / "pass", dst, symlinks=True)
    if name != "pass":
        for src in (FIX / name).rglob("*"):  # overlay files replace pass files
            target = dst / src.relative_to(FIX / name)
            if not src.is_dir() and os.path.lexists(target):
                target.unlink()
        shutil.copytree(FIX / name, dst, symlinks=True, dirs_exist_ok=True)
        rm = dst / "REMOVE"
        if rm.exists():
            for rel in rm.read_text().split():
                p = dst / rel
                if p.is_symlink() or p.is_file():
                    p.unlink()
                else:
                    shutil.rmtree(p)
            rm.unlink()
    return dst


def run_checks(name, env=None):
    with tempfile.TemporaryDirectory() as tmp:
        d = build(name, tmp)
        e = {
            "PATH": os.environ["PATH"],
            "SYSROOT": str(d / "root"),
            "DMESG_CMD": f"cat {d / 'dmesg.txt'}",
            "MAPS_PID": "1234",
            "PIN_STATE": str(d / "pin.state"),
            "PIN_CONF": str(d / "pin.conf"),
            "PIN_WAIT": "0",
            "SUSPEND_WAIT": "0",
            "EGLINFO_FILE": str(d / "eglinfo.txt"),
            "GENPD_SUMMARY_FILE": str(d / "pm_genpd_summary.txt"),
            "PON_REASON_PATH": str(d / "pon-reason.txt"),
        }
        e.update(env or {})
        return subprocess.run([str(SCRIPT), "g0"], env=e, capture_output=True, text=True)


def run_cycles(report):
    e = {"PATH": os.environ["PATH"], "TRACE_REPORT": str(report)}
    return subprocess.run([str(SCRIPT), "cycles", "10"], env=e, capture_output=True, text=True)


class GpuChecks(unittest.TestCase):
    def test_pass_fixture_all_pass(self):
        r = run_checks("pass")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("FAIL", r.stdout)
        for cid in ["gxclkctl-bound", "gmu-genpd", "gx-gdsc-summary", "no-oops", "no-minus19",
                    "no-gx-warn", "renderer", "zap", "pstore", "hung-task", "dpm-watchdog",
                    "suspend-hang-gpu", "probe", "pin-released", "shell-on-gpu",
                    "runtime-suspends"]:
            self.assertRegex(r.stdout, rf"(?m)^PASS {cid} ", msg=cid)
        self.assertRegex(r.stdout, r"(?m)^INFO fuse speed_bin@0x138=2a000000")
        self.assertRegex(r.stdout, r"(?m)^INFO pon-reason PON_REASON=hard-reset")
        self.assertRegex(r.stdout, r"(?m)^PASS gmu-genpd 3d37000\.gmu ")
        self.assertNotIn("unrelated-warnings", r.stdout)

    def test_each_fail_fixture_fails_its_check(self):
        for cid in ["gxclkctl-bound", "gmu-genpd", "no-oops", "no-minus19", "no-gx-warn",
                    "renderer", "zap", "pstore", "probe", "pin-released", "shell-on-gpu",
                    "runtime-suspends", "gx-gdsc-summary", "hung-task", "dpm-watchdog"]:
            r = run_checks(f"fail-{cid}")
            self.assertEqual(r.returncode, 1, cid)
            self.assertRegex(r.stdout, rf"(?m)^FAIL {cid} ", msg=cid)
            self.assertEqual(r.stdout.count("FAIL"), 1, f"{cid}: only its own check fails\n{r.stdout}")

    def test_control_row_on_package_kernel_shape(self):
        r = run_checks("control")  # -19 present, genpd:1 absent, contract 1-5 pass
        self.assertRegex(r.stdout, r"(?m)^FAIL no-minus19 ")
        self.assertRegex(r.stdout, r"(?m)^FAIL gmu-genpd ")
        self.assertRegex(r.stdout, r"(?m)^FAIL gxclkctl-bound ")
        for cid in ["probe", "zap", "renderer", "pin-released", "shell-on-gpu"]:
            self.assertRegex(r.stdout, rf"(?m)^PASS {cid} ")
        self.assertEqual(r.returncode, 1)

    def test_pon_reason_absent_is_info_not_fail(self):
        r = run_checks("pass", env={"PON_REASON_PATH": ""})
        self.assertRegex(r.stdout, r"(?m)^INFO pon-reason not-readable")
        self.assertEqual(r.returncode, 0)

    def test_dpm_watchdog_naming_gpu_is_reported(self):
        r = run_checks("fail-dpm-gpu")
        self.assertRegex(r.stdout, r"(?m)^FAIL suspend-hang-gpu ")

    def test_dpm_device_timeout_naming_gpu_fails(self):
        for fx in ["fail-dpm-timeout", "fail-dpm-resume-gmu"]:
            r = run_checks(fx)
            self.assertRegex(r.stdout, r"(?m)^FAIL suspend-hang-gpu ", msg=fx)
            self.assertEqual(r.stdout.count("FAIL"), 1, f"{fx}\n{r.stdout}")

    def test_dpm_timeout_on_other_device_passes(self):
        r = run_checks("dpm-non-gpu")  # display device; 3d00000xgpu (dot must be literal)
        self.assertRegex(r.stdout, r"(?m)^PASS suspend-hang-gpu none")

    def test_unrelated_warnings_are_info_not_fail(self):
        r = run_checks("unrelated-warnings")  # real DSI-PHY + notifier WARN blocks
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertRegex(r.stdout, r"(?m)^PASS no-oops none")
        self.assertRegex(r.stdout, r"(?m)^INFO unrelated-warnings 2$")

    def test_gpu_warning_stack_fails_no_oops(self):
        r = run_checks("fail-no-oops-gpu")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertRegex(r.stdout, r"(?m)^FAIL no-oops .*a6xx_gmu")
        self.assertEqual(r.stdout.count("FAIL"), 1, r.stdout)

    def test_gmu_genpd_found_at_any_gmu_address(self):
        r = run_checks("gmu-genpd-3d6a000")
        self.assertRegex(r.stdout, r"(?m)^PASS gmu-genpd 3d6a000\.gmu ")
        r = run_checks("fail-gmu-genpd-3d6a000")
        self.assertRegex(r.stdout, r"(?m)^FAIL gmu-genpd .*3d6a000\.gmu")

    def test_pin_mode_always_is_info(self):
        r = run_checks("pin-mode-always")  # rollback setting: no state file
        self.assertRegex(r.stdout, r"(?m)^INFO pin-released mode=always")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_runtime_suspends_pinned_is_info(self):
        r = run_checks("pinned-control-on")
        self.assertRegex(r.stdout, r"(?m)^INFO runtime-suspends control=on")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_gdsc_unreadable_without_sudo_is_fail_not_prompt(self):
        r = run_checks("pass", env={"GENPD_SUMMARY_FILE": "", "SYSROOT": "/nonexistent-root"})
        self.assertRegex(r.stdout, r"(?m)^FAIL gx-gdsc-summary .*(no sudo|unreadable)")

    def test_empty_dmesg_fails_absence_checks(self):
        for env in ({"DMESG_CMD": "true"}, {"DMESG_CMD": "false"}):
            r = run_checks("pass", env=env)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertRegex(r.stdout, r"(?m)^FAIL dmesg-readable dmesg unavailable")
            for cid in ["no-oops", "no-minus19", "no-gx-warn", "zap", "suspend-hang-gpu"]:
                self.assertRegex(r.stdout, rf"(?m)^FAIL {cid} dmesg unavailable", msg=cid)

    def test_renderer_accepts_mesa_adreno_tm_830(self):
        r = run_checks("pass")
        self.assertRegex(r.stdout, r"(?m)^PASS renderer Adreno 830")

    def test_renderer_ignores_software_device_in_device_platform(self):
        # root's eglinfo -B on the 2026-10-29 candidate: Adreno everywhere,
        # plus Mesa's llvmpipe listed as a second EGL device
        r = run_checks("renderer-device-swrast")
        self.assertRegex(r.stdout, r"(?m)^PASS renderer Adreno 830")

    def test_renderer_fails_when_any_platform_is_software(self):
        r = run_checks("renderer-mixed")
        self.assertRegex(r.stdout, r"(?m)^FAIL renderer software renderer")

    def test_cycles_missing_report_fails(self):
        r = run_cycles("/nonexistent/report")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("cycles=", r.stdout)
        self.assertIn("unreadable", r.stderr)

    def test_cycles_no_events_prints_zeros(self):
        with tempfile.NamedTemporaryFile("w") as f:
            r = run_cycles(f.name)
        self.assertIn("cycles=0 suspend=0 resume=0", r.stdout)

    def test_cycles_parses_trace_report(self):
        r = run_cycles(FIX / "trace" / "report.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cycles=7 suspend=7 resume=7", r.stdout)

    def test_cycles_recording_exits_zero_and_cleans_up(self):
        # the soak tick drops a window whose helper exits nonzero
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "bin").mkdir()
            (d / "tmp").mkdir()
            fake = d / "bin" / "trace-cmd"
            fake.write_text('#!/bin/sh\n[ "$1" = report ] && cat "%s"\nexit 0\n'
                            % (FIX / "trace" / "report.txt"))
            fake.chmod(0o755)
            e = {"PATH": f"{d / 'bin'}:{os.environ['PATH']}", "TMPDIR": str(d / "tmp")}
            r = subprocess.run([str(SCRIPT), "cycles", "1"], env=e, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stderr, "")
            self.assertIn("cycles=7 suspend=7 resume=7", r.stdout)
            self.assertEqual(list((d / "tmp").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
