"""V17 publishes the primary KNALDGAS products at the results root."""

from pathlib import Path
import subprocess
import tempfile
import unittest
import shutil


ROOT = Path(__file__).resolve().parent


class V17FlatOutputTests(unittest.TestCase):
    def make_package(self, root: Path) -> None:
        (root / "v17/data").mkdir(parents=True)
        for name in ("go17.sh", "v17/run.sh"):
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        (root / "v17/data/stars_gaia_dr3_g75.csv").write_text("fixture")
        analyser = root / "v17/analyse.sh"
        analyser.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ ${1:-} == --version ]]; then\n"
            "  echo 'Wide-field solver 0.17.0'\n"
            "  exit 0\n"
            "fi\n"
            "output=''\n"
            "while [[ $# -gt 0 ]]; do\n"
            "  if [[ $1 == --output ]]; then output=$2; shift 2; else shift; fi\n"
            "done\n"
            "mkdir -p -- \"$output\"\n"
            "printf 'pdf' > \"$output/report.pdf\"\n"
            "printf 'solution' > \"$output/solution.fits\"\n"
            "printf 'annotated' > \"$output/solution_annotated.fits\"\n",
            encoding="utf-8",
        )
        analyser.chmod(0o755)

    def test_primary_products_are_flat_and_include_the_input_name(self):
        """Removing flat publication must leave no matching root-level products."""
        with tempfile.TemporaryDirectory(prefix="v17 flat products ") as temporary:
            root = Path(temporary) / "repo"
            self.make_package(root)
            image = root / "20261012 sky RGB.fits.bz2"
            image.write_bytes(b"image")
            results = Path(temporary) / "results"

            completed = subprocess.run(
                [str(root / "go17.sh"), str(image), "--results-dir", str(results)],
                cwd="/tmp",
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            flat = sorted(path for path in results.iterdir() if path.is_file())
            products = [path for path in flat if path.name != "stars.sqlite"]
            self.assertEqual(len(products), 3, [path.name for path in products])
            self.assertEqual(
                {path.name.rsplit("__", 1)[1] for path in products},
                {"report.pdf", "solution.fits", "solution_annotated.fits"},
            )
            for path in products:
                self.assertIn("20261012_sky_RGB.fits-v0.17.0-", path.name)
                self.assertEqual(path.parent, results)
                self.assertIn(str(path), completed.stdout)
                nested = next((results / "runs").glob(f"*/analysis/{path.name.rsplit('__', 1)[1]}"))
                self.assertNotEqual(path.stat().st_ino, nested.stat().st_ino)

    def test_flat_only_reuses_stable_names_without_creating_run_folders(self):
        """Restoring timestamp/run nesting must break the KNALDGAS flat workflow."""
        with tempfile.TemporaryDirectory(prefix="v17 stable flat ") as temporary:
            root = Path(temporary) / "repo"
            self.make_package(root)
            image = root / "20261012 sky RGB.fits.bz2"
            image.write_bytes(b"image")
            results = Path(temporary) / "results"
            command = [str(root / "v17/run.sh"), "--flat-only", str(image),
                       "--results-dir", str(results)]

            first = subprocess.run(command, cwd="/tmp", text=True,
                                   capture_output=True, check=False)
            second = subprocess.run(command, cwd="/tmp", text=True,
                                    capture_output=True, check=False)

            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertFalse((results / "runs").exists())
            self.assertFalse((results / "stars.sqlite").exists())
            self.assertEqual(
                sorted(path.name for path in results.iterdir()),
                [
                    "20261012_sky_RGB__report.pdf",
                    "20261012_sky_RGB__solution.fits",
                    "20261012_sky_RGB__solution_annotated.fits",
                ],
            )
            self.assertIn(str(results / "20261012_sky_RGB__report.pdf"), second.stdout)


if __name__ == "__main__":
    unittest.main()
