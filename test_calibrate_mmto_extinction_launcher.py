from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "calibrate_mmto_extinction.sh"
SCRIPT = ROOT / "scripts" / "calibrate_nightly_extinction.py"


class CalibrateMmtoExtinctionLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.database = self.work / "stars.sqlite"
        self.manifest = self.work / "manifest.sqlite"
        self.output = self.work / "sidecar"
        self.database.touch()
        self.manifest.touch()
        self.bin_dir = self.work / "bin"
        self.bin_dir.mkdir()
        self.uv_log = self.work / "uv-invocations.txt"
        fake_uv = self.bin_dir / "uv"
        fake_uv.write_text(
            "#!/usr/bin/env bash\n"
            "printf '%s\\n' \"$*\" >> \"$FAKE_UV_LOG\"\n",
            encoding="utf-8",
        )
        fake_uv.chmod(0o755)

    def run_launcher(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment["PATH"] = f"{self.bin_dir}:{environment['PATH']}"
        environment["FAKE_UV_LOG"] = str(self.uv_log)
        return subprocess.run(
            ["bash", str(LAUNCHER), *arguments],
            cwd=self.work,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_forwards_explicit_overrides_from_another_working_directory(self) -> None:
        result = self.run_launcher(
            "--database",
            str(self.database),
            "--manifest",
            str(self.manifest),
            "--output",
            str(self.output),
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        invocation = self.uv_log.read_text(encoding="utf-8").strip()
        self.assertIn(f"run --project {ROOT} --frozen python", invocation)
        self.assertIn(
            f"{ROOT / 'scripts' / 'calibrate_nightly_extinction.py'}",
            invocation,
        )
        self.assertIn(f"--database {self.database}", invocation)
        self.assertIn(f"--manifest {self.manifest}", invocation)
        self.assertIn(f"--output {self.output}", invocation)

    def test_refuses_nonempty_explicit_output_before_invoking_python(self) -> None:
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("historical\n", encoding="utf-8")

        result = self.run_launcher(
            "--database",
            str(self.database),
            "--manifest",
            str(self.manifest),
            "--output",
            str(self.output),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not empty", result.stdout)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "historical\n")
        self.assertFalse(self.uv_log.exists())

    def test_no_arguments_delegate_timestamped_defaults_to_python(self) -> None:
        result = self.run_launcher()

        self.assertEqual(result.returncode, 0, result.stdout)
        invocation = self.uv_log.read_text(encoding="utf-8").strip()
        self.assertEqual(
            invocation,
            f"run --project {ROOT} --frozen python "
            f"{ROOT / 'scripts' / 'calibrate_nightly_extinction.py'}",
        )

    def test_direct_script_execution_can_import_repository_packages(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=self.work,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("--manifest", result.stdout)


if __name__ == "__main__":
    unittest.main()
