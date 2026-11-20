"""Clean-clone bootstrap behavior without network or dependency downloads."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parent.parent
LIBRARY = ROOT / "v25/scripts/quickstart.sh"


class QuickstartTests(unittest.TestCase):
    def run_bash(
        self,
        body: str,
        *,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        run_env = dict(os.environ)
        run_env["QUICKSTART_LIBRARY"] = str(LIBRARY)
        if env:
            run_env.update(env)
        return subprocess.run(
            ["bash", "-c", textwrap.dedent(body)],
            cwd=ROOT,
            env=run_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_accepts_both_certified_ubuntu_versions(self) -> None:
        for version in ("24.04", "26.04"):
            with self.subTest(version=version), tempfile.TemporaryDirectory() as tmp:
                release = Path(tmp) / "os-release"
                release.write_text(f'ID=ubuntu\nVERSION_ID="{version}"\n')
                completed = self.run_bash(
                    'source "$QUICKSTART_LIBRARY"\n'
                    'quickstart_platform "$OS_RELEASE" x86_64',
                    env={"OS_RELEASE": str(release)},
                )
                self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_rejects_unsupported_platform_before_installation(self) -> None:
        cases = (
            ("ubuntu", "22.04", "x86_64"),
            ("debian", "24.04", "x86_64"),
            ("ubuntu", "24.04", "aarch64"),
        )
        for system_id, version, arch in cases:
            with (
                self.subTest(system_id=system_id, version=version, arch=arch),
                tempfile.TemporaryDirectory() as tmp,
            ):
                release = Path(tmp) / "os-release"
                release.write_text(
                    f'ID={system_id}\nVERSION_ID="{version}"\n', encoding="utf-8"
                )
                completed = self.run_bash(
                    'source "$QUICKSTART_LIBRARY"\n'
                    'quickstart_install_uv() { echo INSTALLED; }\n'
                    'quickstart_platform "$OS_RELEASE" "$ARCH" && '
                    'quickstart_install_uv /tmp/unused',
                    env={"OS_RELEASE": str(release), "ARCH": arch},
                )
                self.assertEqual(completed.returncode, 1, completed.stdout)
                self.assertNotIn("INSTALLED", completed.stdout)
                self.assertIn("Ubuntu 24.04 or 26.04", completed.stdout)
                self.assertIn("x86-64", completed.stdout)

    def test_missing_prerequisite_has_one_ubuntu_remedy(self) -> None:
        required = ("bash", "git", "tar", "sha256sum", "curl")
        true_path = Path(shutil.which("true") or "/bin/true")
        for missing in ("bash", "git", "tar", "sha256sum", "curl"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                bin_dir = root / "bin"
                bin_dir.mkdir()
                for name in required:
                    if name != missing:
                        (bin_dir / name).symlink_to(true_path)
                ca_file = root / "ca-certificates.crt"
                ca_file.write_text("fixture", encoding="utf-8")
                completed = self.run_bash(
                    'source "$QUICKSTART_LIBRARY"\n'
                    'PATH="$FIXTURE_PATH" quickstart_requirements "$CA_FILE"',
                    env={"FIXTURE_PATH": str(bin_dir), "CA_FILE": str(ca_file)},
                )
                self.assertEqual(completed.returncode, 1, completed.stdout)
                remedies = [
                    line for line in completed.stdout.splitlines()
                    if "sudo apt-get install" in line
                ]
                self.assertEqual(len(remedies), 1, completed.stdout)
                expected_package = {
                    "bash": "bash",
                    "curl": "curl",
                    "git": "git",
                    "sha256sum": "coreutils",
                    "tar": "tar",
                }[missing]
                self.assertIn(expected_package, remedies[0])

    def test_missing_ca_certificates_has_one_ubuntu_remedy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            true_path = Path(shutil.which("true") or "/bin/true")
            for name in ("bash", "git", "tar", "sha256sum", "curl"):
                (bin_dir / name).symlink_to(true_path)
            completed = self.run_bash(
                'source "$QUICKSTART_LIBRARY"\n'
                'PATH="$FIXTURE_PATH" quickstart_requirements /missing/ca.pem',
                env={"FIXTURE_PATH": str(bin_dir)},
            )
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertEqual(completed.stdout.count("sudo apt-get install"), 1)
            self.assertIn("ca-certificates", completed.stdout)

    def test_pins_reviewed_uv_archive(self) -> None:
        completed = self.run_bash(
            'source "$QUICKSTART_LIBRARY"\n'
            'printf "%s\\n%s\\n%s\\n" "$QUICKSTART_UV_VERSION" '
            '"$QUICKSTART_UV_SHA256" "$QUICKSTART_UV_URL"'
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual(
            completed.stdout.splitlines(),
            [
                "0.9.30",
                "8b3762374972daa7a74bbc6896cc73229ca69a07403dd9f9ea3805a51ffd7582",
                "https://github.com/astral-sh/uv/releases/download/0.9.30/"
                "uv-x86_64-unknown-linux-gnu.tar.gz",
            ],
        )

    def test_checksum_failure_never_installs_uv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "altered.tar.gz"
            archive.write_bytes(b"not the reviewed uv archive")
            completed = self.run_bash(
                'source "$QUICKSTART_LIBRARY"\n'
                'quickstart_fetch() { cp "$BAD_ARCHIVE" "$2"; }\n'
                'quickstart_install_uv "$REPOSITORY_ROOT"',
                env={"BAD_ARCHIVE": str(archive), "REPOSITORY_ROOT": str(root)},
            )
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertIn("checksum", completed.stdout.lower())
            self.assertFalse((root / ".tools/uv/0.9.30/uv").exists())

    def test_interrupted_download_never_installs_uv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed = self.run_bash(
                'source "$QUICKSTART_LIBRARY"\n'
                'quickstart_fetch() { printf partial > "$2"; return 23; }\n'
                'quickstart_install_uv "$REPOSITORY_ROOT"',
                env={"REPOSITORY_ROOT": str(root)},
            )
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertIn("Could not download", completed.stdout)
            self.assertFalse((root / ".tools/uv/0.9.30/uv").exists())

    def test_existing_verified_uv_is_reused_without_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            uv = root / ".tools/uv/0.9.30/uv"
            uv.parent.mkdir(parents=True)
            uv.write_text("#!/usr/bin/env bash\necho 'uv 0.9.30'\n", encoding="utf-8")
            uv.chmod(0o755)
            marker = root / "downloaded"
            completed = self.run_bash(
                'source "$QUICKSTART_LIBRARY"\n'
                'quickstart_fetch() { : > "$DOWNLOAD_MARKER"; return 99; }\n'
                'quickstart_install_uv "$REPOSITORY_ROOT"',
                env={"DOWNLOAD_MARKER": str(marker), "REPOSITORY_ROOT": str(root)},
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(completed.stdout.strip(), str(uv))
            self.assertFalse(marker.exists())

    def test_success_uses_local_state_and_prints_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            environment = root / "environment.txt"
            completed = self.run_bash(
                'source "$QUICKSTART_LIBRARY"\n'
                'quickstart_platform() { return 0; }\n'
                'quickstart_requirements() { return 0; }\n'
                'quickstart_install_uv() { echo /bin/true; }\n'
                'quickstart_sync() { '
                'printf "%s\\n%s\\n%s\\n%s\\n%s\\n" '
                '"${VIRTUAL_ENV-unset}" "$UV_CACHE_DIR" '
                '"$UV_PYTHON_INSTALL_DIR" "$UV_PROJECT_ENVIRONMENT" '
                '"${UV_MANAGED_PYTHON-unset}" '
                '> "$ENVIRONMENT_FILE"; }\n'
                'quickstart_demo() { mkdir -p "$3"; : > "$3/report.pdf"; }\n'
                'quickstart_main "$REPOSITORY_ROOT"',
                env={
                    "ENVIRONMENT_FILE": str(environment),
                    "REPOSITORY_ROOT": str(root),
                    "VIRTUAL_ENV": "/wrong/environment",
                },
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            values = environment.read_text(encoding="utf-8").splitlines()
            self.assertEqual(values[0], "unset")
            self.assertEqual(values[1], str(root / ".tools/cache"))
            self.assertEqual(values[2], str(root / ".tools/python"))
            self.assertEqual(values[3], str(root / "v25/.venv"))
            self.assertEqual(values[4], "1")
            report = root / "results/quickstart-v25/report.pdf"
            self.assertTrue(report.is_file())
            self.assertIn(str(report), completed.stdout)
            self.assertIn("Quick start complete", completed.stdout)
            self.assertIn("./go25.sh /full/path/to/image.fits", completed.stdout)

    def test_sync_failure_never_prints_success(self) -> None:
        completed = self.run_bash(
            'source "$QUICKSTART_LIBRARY"\n'
            'quickstart_platform() { return 0; }\n'
            'quickstart_requirements() { return 0; }\n'
            'quickstart_install_uv() { echo /bin/true; }\n'
            'quickstart_sync() { return 7; }\n'
            'quickstart_demo() { echo DEMO-RAN; }\n'
            'quickstart_main /tmp/quickstart-sync-failure'
        )
        self.assertEqual(completed.returncode, 7, completed.stdout)
        self.assertNotIn("DEMO-RAN", completed.stdout)
        self.assertNotIn("Quick start complete", completed.stdout)

    def test_demo_failure_never_prints_success(self) -> None:
        completed = self.run_bash(
            'source "$QUICKSTART_LIBRARY"\n'
            'quickstart_platform() { return 0; }\n'
            'quickstart_requirements() { return 0; }\n'
            'quickstart_install_uv() { echo /bin/true; }\n'
            'quickstart_sync() { return 0; }\n'
            'quickstart_demo() { return 8; }\n'
            'quickstart_main /tmp/quickstart-demo-failure'
        )
        self.assertEqual(completed.returncode, 8, completed.stdout)
        self.assertNotIn("Quick start complete", completed.stdout)

    def test_missing_report_never_prints_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = self.run_bash(
                'source "$QUICKSTART_LIBRARY"\n'
                'quickstart_platform() { return 0; }\n'
                'quickstart_requirements() { return 0; }\n'
                'quickstart_install_uv() { echo /bin/true; }\n'
                'quickstart_sync() { return 0; }\n'
                'quickstart_demo() { return 0; }\n'
                'quickstart_main "$REPOSITORY_ROOT"',
                env={"REPOSITORY_ROOT": tmp},
            )
            self.assertEqual(completed.returncode, 1, completed.stdout)
            self.assertIn("report.pdf", completed.stdout)
            self.assertNotIn("Quick start complete", completed.stdout)


if __name__ == "__main__":
    unittest.main()
