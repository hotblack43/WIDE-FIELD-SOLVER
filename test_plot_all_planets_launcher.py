from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "plot_ALL_planets.sh"


class PlotAllPlanetsLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.database = self.work / "stars.sqlite"
        self.database.touch()
        self.nightly_calibration = self.work / "nightly-calibration"
        self.nightly_calibration.mkdir()
        self.output = self.work / "plots"
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

    def run_launcher(self, *extra):
        environment = dict(os.environ)
        environment["PATH"] = f"{self.bin_dir}:{environment['PATH']}"
        environment["FAKE_UV_LOG"] = str(self.uv_log)
        return subprocess.run(
            [
                "bash", str(LAUNCHER),
                "--database", str(self.database),
                "--nightly-calibration", str(self.nightly_calibration),
                "--output", str(self.output),
                *extra,
            ],
            cwd=self.work,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_runs_extinction_and_distance_corrected_product_for_all_channels(self):
        result = self.run_launcher()

        self.assertEqual(result.returncode, 0, result.stdout)
        invocations = self.uv_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(invocations), 5)
        self.assertTrue(all(
            f"run --project {ROOT} --frozen" in line
            for line in invocations
        ))
        for channel in "RGB":
            channel_runs = [
                line for line in invocations
                if f"--channel {channel}" in line
            ]
            self.assertEqual(len(channel_runs), 1)
            self.assertTrue(all(
                f"--output {self.output / channel}" in line
                for line in channel_runs
            ))
            nightly_run = channel_runs[0]
            self.assertIn(
                "--extinction-corrected-distance-corrected", nightly_run
            )
            self.assertNotIn(" --extinction-corrected ", f" {nightly_run} ")
            self.assertIn(
                f"--nightly-calibration {self.nightly_calibration}",
                nightly_run,
            )
            self.assertNotIn(" --stellar-calibrated-distance-corrected", nightly_run)
        colour_runs = [
            line for line in invocations
            if "scripts/plot_planet_colours.py" in line
        ]
        self.assertEqual(len(colour_runs), 1)
        self.assertIn(f"--input-root {self.output}", colour_runs[0])
        self.assertIn(f"--output {self.output}", colour_runs[0])
        matched_runs = [
            line for line in invocations
            if "scripts/plot_brightness_matched_planet_extinction.py" in line
        ]
        self.assertEqual(len(matched_runs), 1)
        self.assertIn(
            f"--stellar-measurements "
            f"{self.nightly_calibration / 'calibration_star_measurements.csv'}",
            matched_runs[0],
        )
        self.assertIn(f"--planet-root {self.output}", matched_runs[0])
        self.assertIn(f"--output {self.output}", matched_runs[0])
        self.assertIn("All planet plots completed", result.stdout)
        self.assertTrue((self.output / "plot_ALL_planets.log").is_file())

    def test_refuses_to_overwrite_a_nonempty_output_directory(self):
        self.output.mkdir()
        sentinel = self.output / "keep-me.txt"
        sentinel.write_text("historical evidence\n", encoding="utf-8")

        result = self.run_launcher()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not empty", result.stdout)
        self.assertEqual(
            sentinel.read_text(encoding="utf-8"),
            "historical evidence\n",
        )
        self.assertFalse(self.uv_log.exists())


if __name__ == "__main__":
    unittest.main()
