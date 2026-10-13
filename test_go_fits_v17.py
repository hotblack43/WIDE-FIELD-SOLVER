"""Explicit-FITS launcher behavior for the v17 solver."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent


class ExplicitFitsV17LauncherTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        launcher = root / "go_fits_v17.sh"
        shutil.copy2(ROOT / "go_fits_v17.sh", launcher)
        delegate = root / "go17.sh"
        delegate.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "printf '%s\\0' \"$@\" > \"$WFS_TEST_CAPTURE\"\n"
            "mkdir -p -- \"$WFS_TEST_ANALYSIS\"\n"
            "touch -- \"$WFS_TEST_ANALYSIS/astrometry_overlay.png\"\n"
            "touch -- \"$WFS_TEST_ANALYSIS/report_sky_overlay.png\"\n"
            "touch -- \"$WFS_TEST_ANALYSIS/solution_annotated.fits\"\n"
            "printf 'Images and reports: %s\\n' \"$WFS_TEST_ANALYSIS\"\n",
            encoding="utf-8",
        )
        delegate.chmod(0o755)
        capture = root / "arguments.bin"
        analysis = root / "solver results" / "runs" / "run-1" / "analysis"
        return launcher, capture, analysis

    def test_help_describes_designated_fits_and_annotated_products(self):
        completed = subprocess.run(
            ["bash", str(ROOT / "go_fits_v17.sh"), "--help"],
            cwd="/tmp",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("FITS [FITS ...]", completed.stdout)
        self.assertIn("astrometry_overlay.png", completed.stdout)
        self.assertIn("report_sky_overlay.png", completed.stdout)
        self.assertIn("solution_annotated.fits", completed.stdout)
        self.assertIn("KNALDGAS linear RGB", completed.stdout)

    def test_direct_fits_and_compressed_fits_are_forwarded_together(self):
        with tempfile.TemporaryDirectory(prefix="explicit fits direct ") as temporary:
            root = Path(temporary)
            launcher, capture, analysis = self.make_fixture(root)
            first = root / "first.fit"
            second = root / "second.fits.bz2"
            first.touch()
            second.touch()
            environment = dict(
                os.environ,
                WFS_TEST_CAPTURE=str(capture),
                WFS_TEST_ANALYSIS=str(analysis),
            )

            completed = subprocess.run(
                [str(launcher), str(first), str(second)],
                cwd="/tmp",
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                capture.read_bytes().split(b"\0")[:-1],
                [os.fsencode(first), os.fsencode(second)],
            )

    def test_quoted_wildcard_expands_and_forwards_native_v17_options(self):
        with tempfile.TemporaryDirectory(prefix="explicit fits ") as temporary:
            root = Path(temporary)
            launcher, capture, analysis = self.make_fixture(root)
            first = root / "first image.fits"
            second = root / "second.fits"
            first.touch()
            second.touch()
            (root / "not-fits.jpg").touch()
            results = root / "results"
            environment = dict(
                os.environ,
                WFS_TEST_CAPTURE=str(capture),
                WFS_TEST_ANALYSIS=str(analysis),
            )

            completed = subprocess.run(
                [
                    str(launcher),
                    str(root / "*.fits"),
                    "--results-dir",
                    str(results),
                    "--channel-order",
                    "RG1G2B",
                ],
                cwd="/tmp",
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            forwarded = capture.read_bytes().split(b"\0")[:-1]
            self.assertEqual(
                forwarded,
                [
                    os.fsencode(first),
                    os.fsencode(second),
                    b"--results-dir",
                    os.fsencode(results),
                    b"--channel-order",
                    b"RG1G2B",
                ],
            )

    def test_success_reports_existing_annotated_products(self):
        with tempfile.TemporaryDirectory(prefix="explicit fits products ") as temporary:
            root = Path(temporary)
            launcher, capture, analysis = self.make_fixture(root)
            image = root / "image.fits"
            image.touch()
            environment = dict(
                os.environ,
                WFS_TEST_CAPTURE=str(capture),
                WFS_TEST_ANALYSIS=str(analysis),
            )

            completed = subprocess.run(
                [str(launcher), str(image)],
                cwd="/tmp",
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(f"Annotated astrometry: {analysis / 'astrometry_overlay.png'}", completed.stdout)
            self.assertIn(f"Annotated sky: {analysis / 'report_sky_overlay.png'}", completed.stdout)
            self.assertIn(f"Annotated FITS: {analysis / 'solution_annotated.fits'}", completed.stdout)

    def test_unmatched_wildcard_rejects_batch_before_solver_starts(self):
        with tempfile.TemporaryDirectory(prefix="explicit fits unmatched ") as temporary:
            root = Path(temporary)
            launcher, capture, analysis = self.make_fixture(root)
            image = root / "image.fits"
            image.touch()
            environment = dict(
                os.environ,
                WFS_TEST_CAPTURE=str(capture),
                WFS_TEST_ANALYSIS=str(analysis),
            )

            completed = subprocess.run(
                [str(launcher), str(image), str(root / "missing-*.fits")],
                cwd="/tmp",
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
            self.assertFalse(capture.exists(), "go17 must not receive a partial batch")

    def test_invalid_suffix_rejects_batch_before_solver_starts(self):
        with tempfile.TemporaryDirectory(prefix="explicit fits invalid ") as temporary:
            root = Path(temporary)
            launcher, capture, analysis = self.make_fixture(root)
            image = root / "image.fits"
            invalid = root / "preview.jpg"
            image.touch()
            invalid.touch()
            environment = dict(
                os.environ,
                WFS_TEST_CAPTURE=str(capture),
                WFS_TEST_ANALYSIS=str(analysis),
            )

            completed = subprocess.run(
                [str(launcher), str(image), str(invalid)],
                cwd="/tmp",
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
            self.assertFalse(capture.exists(), "go17 must not receive a partial batch")


if __name__ == "__main__":
    unittest.main()
