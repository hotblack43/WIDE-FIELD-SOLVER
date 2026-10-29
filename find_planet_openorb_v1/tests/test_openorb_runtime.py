from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))


class ConfigurationTests(unittest.TestCase):
    def test_primary_and_sensitivity_budgets_are_identity_neutral(self) -> None:
        from find_planet_openorb.openorb_runtime import RangingBudget, audit_config

        cases = (
            ("primary.conf", RangingBudget(5000, 5_000_000, 3, 3600.0)),
            ("half_sigma.conf", RangingBudget(2000, 2_000_000, 3, 1800.0)),
            ("double_sigma.conf", RangingBudget(2000, 2_000_000, 3, 1800.0)),
        )
        for name, budget in cases:
            audit = audit_config(PROJECT / "config" / name, budget)
            self.assertEqual(audit.dynamical_model, "2-body")
            self.assertTrue(all(not enabled for enabled in audit.perturbers.values()))
            self.assertEqual(audit.ephemeris_name, "de441.dat")

    def test_pinned_two_body_source_branch_is_unchanged(self) -> None:
        manifest = json.loads((PROJECT / "openorb-sources.json").read_text())
        expected = manifest["audited_target_dynamics"]["classes/Orbit_class.f90"]
        source = PROJECT / ".vendor/openorb-1.3.0/classes/Orbit_class.f90"
        if source.is_file():
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), expected)
            text = source.read_text(encoding="latin-1")
            start = text.index("SUBROUTINE propagate_Orb_multiple")
            self.assertLess(text.index('CASE ("2-body")', start), text.index('CASE ("n-body")', start))


class RuntimeTests(unittest.TestCase):
    def _installation(self, root: Path, body: str):
        from find_planet_openorb.provenance import OpenOrbInstallation

        executable = root / "oorb"
        executable.write_text("#!/bin/sh\n" + body)
        executable.chmod(0o755)
        data = root / "data"; data.mkdir()
        config = root / "oorb.conf"; config.write_text("planetary_ephemeris_fname: de441.dat\n")
        return OpenOrbInstallation(root, executable, data, config, "fake-sha", root/"build.json", root/"data.json", "v1.3.0", "945178476f016dae8f3981b54a937f61de81360f")

    def test_shell_free_explicit_ranging_command_and_receipt(self) -> None:
        from find_planet_openorb.openorb_runtime import OpenOrbRunSpec, RangingBudget, run_openorb

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installation = self._installation(root, 'printf "%s\\n" "$@"; printf "Accepted sample orbits: 5\\n"; for arg in "$@"; do case "$arg" in --orb-out=*) touch "${arg#--orb-out=}";; esac; done\n')
            input_path = root / "input.mpc3"; input_path.write_text("fixture\n")
            output = root / "run"; output.mkdir()
            spec = OpenOrbRunSpec("ranging", input_path, root/"config.conf", output/"samples.sor", RangingBudget(5, 20, 1, 10.0))
            spec.config_path.write_text("dynamical_model: 2-body\n")
            receipt = run_openorb(spec, installation, output)
            self.assertEqual(receipt.status, "success")
            self.assertIn("--fixran", receipt.command)
            self.assertIn(f"--conf={spec.config_path.resolve()}", receipt.command)
            self.assertEqual(receipt.accepted_samples, 5)
            self.assertTrue((output / "openorb-run-receipt.json").is_file())
            payload = json.loads((output / "openorb-run-receipt.json").read_text())
            self.assertEqual(payload["environment"]["OORB_DATA"], str(installation.data_directory))
            self.assertNotIn("PATH_oorb", payload["environment"])

    def test_zero_exit_incomplete_and_nonzero_are_not_success(self) -> None:
        from find_planet_openorb.openorb_runtime import OpenOrbRunSpec, RangingBudget, run_openorb

        for body, expected in (("exit 0\n", "search_incomplete"), ('echo "***ERROR*** parse failed" >&2\nexit 0\n', "execution_failed"), ("exit 7\n", "execution_failed")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); installation = self._installation(root, body)
                input_path = root/"input.mpc3"; input_path.write_text("fixture\n")
                config = root/"config.conf"; config.write_text("fixture\n")
                output = root/"run"; output.mkdir()
                receipt = run_openorb(OpenOrbRunSpec("ranging",input_path,config,output/"samples.sor",RangingBudget(5,20,1,10)),installation,output)
                self.assertEqual(receipt.status, expected)

    def test_timeout_is_recorded_and_process_group_stopped(self) -> None:
        from find_planet_openorb.openorb_runtime import OpenOrbRunSpec, RangingBudget, run_openorb

        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); installation=self._installation(root,"sleep 30\n")
            input_path=root/"input.mpc3"; input_path.write_text("fixture\n")
            config=root/"config.conf"; config.write_text("fixture\n")
            output=root/"run"; output.mkdir()
            receipt=run_openorb(OpenOrbRunSpec("ranging",input_path,config,output/"samples.sor",RangingBudget(5,20,1,0.05)),installation,output)
            self.assertEqual(receipt.status,"timed_out")
            self.assertTrue(receipt.terminated)


if __name__ == "__main__": unittest.main()
