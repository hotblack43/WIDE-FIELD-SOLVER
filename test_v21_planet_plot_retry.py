"""V21 planet plotting retries only transient Horizons transport failures."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "v21" / "plot_ALL_planets_v21.sh"


class V21PlanetPlotRetryTests(unittest.TestCase):
    def run_launcher(self, plot_body: str):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "v21").mkdir()
        shutil.copy2(LAUNCHER, root / "v21" / LAUNCHER.name)
        plot = root / "plot_ALL_planets.sh"
        plot.write_text(plot_body, encoding="utf-8")
        plot.chmod(0o755)
        database = root / "stars.sqlite"
        database.touch()
        nightly = root / "nightly"
        nightly.mkdir()
        output = root / "planet-output"
        environment = dict(os.environ, V21_HORIZONS_RETRY_DELAY_SECONDS="0")
        completed = subprocess.run(
            [
                "bash", str(root / "v21" / LAUNCHER.name),
                "--database", str(database),
                "--nightly-calibration", str(nightly),
                "--output", str(output),
            ],
            cwd=root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        return root, output, completed

    def test_transient_horizons_timeout_is_retried_and_failed_attempt_preserved(self):
        root, output, completed = self.run_launcher(
            """#!/usr/bin/env bash
set -eu
count_file="$(dirname "$0")/calls"
count=0
[[ ! -f "$count_file" ]] || count=$(cat "$count_file")
count=$((count + 1))
printf '%s\n' "$count" > "$count_file"
while (($#)); do
    if [[ $1 == --output ]]; then output=$2; shift 2; else shift; fi
done
mkdir -p "$output"
if ((count == 1)); then
    printf '%s\n' 'requests.exceptions.ConnectTimeout: temporary' > "$output/plot_ALL_planets.log"
    exit 1
fi
printf '%s\n' complete > "$output/success.txt"
"""
        )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual((root / "calls").read_text().strip(), "2")
        self.assertEqual((output / "success.txt").read_text().strip(), "complete")
        failed = Path(f"{output}-failed-attempt-1")
        self.assertIn("ConnectTimeout", (failed / "plot_ALL_planets.log").read_text())

    def test_non_network_failure_is_not_retried(self):
        root, output, completed = self.run_launcher(
            """#!/usr/bin/env bash
set -eu
count_file="$(dirname "$0")/calls"
count=0
[[ ! -f "$count_file" ]] || count=$(cat "$count_file")
count=$((count + 1))
printf '%s\n' "$count" > "$count_file"
while (($#)); do
    if [[ $1 == --output ]]; then output=$2; shift 2; else shift; fi
done
mkdir -p "$output"
printf '%s\n' 'ValueError: malformed Horizons response' > "$output/plot_ALL_planets.log"
exit 1
"""
        )

        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertEqual((root / "calls").read_text().strip(), "1")
        self.assertFalse(output.exists())
        self.assertTrue(Path(f"{output}-failed-attempt-1").is_dir())

    def test_retryable_horizons_http_status_is_retried(self):
        root, output, completed = self.run_launcher(
            """#!/usr/bin/env bash
set -eu
count_file="$(dirname "$0")/calls"
count=0
[[ ! -f "$count_file" ]] || count=$(cat "$count_file")
count=$((count + 1))
printf '%s\n' "$count" > "$count_file"
while (($#)); do
    if [[ $1 == --output ]]; then output=$2; shift 2; else shift; fi
done
mkdir -p "$output"
if ((count == 1)); then
    printf '%s\n' 'requests.exceptions.HTTPError: 503 Server Error: Service Unavailable' > "$output/plot_ALL_planets.log"
    exit 1
fi
printf '%s\n' complete > "$output/success.txt"
"""
        )

        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertEqual((root / "calls").read_text().strip(), "2")
        self.assertEqual((output / "success.txt").read_text().strip(), "complete")
        self.assertIn(
            "503 Server Error",
            (
                Path(f"{output}-failed-attempt-1") / "plot_ALL_planets.log"
            ).read_text(),
        )

    def test_transient_failure_stops_after_four_preserved_attempts(self):
        root, output, completed = self.run_launcher(
            """#!/usr/bin/env bash
set -eu
count_file="$(dirname "$0")/calls"
count=0
[[ ! -f "$count_file" ]] || count=$(cat "$count_file")
count=$((count + 1))
printf '%s\n' "$count" > "$count_file"
while (($#)); do
    if [[ $1 == --output ]]; then output=$2; shift 2; else shift; fi
done
mkdir -p "$output"
printf '%s\n' 'requests.exceptions.ReadTimeout: temporary' > "$output/plot_ALL_planets.log"
exit 1
"""
        )

        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertEqual((root / "calls").read_text().strip(), "4")
        self.assertFalse(output.exists())
        self.assertTrue(all(
            Path(f"{output}-failed-attempt-{attempt}").is_dir()
            for attempt in range(1, 5)
        ))

    def test_certificate_failure_is_not_retried(self):
        root, output, completed = self.run_launcher(
            """#!/usr/bin/env bash
set -eu
count_file="$(dirname "$0")/calls"
count=0
[[ ! -f "$count_file" ]] || count=$(cat "$count_file")
count=$((count + 1))
printf '%s\n' "$count" > "$count_file"
while (($#)); do
    if [[ $1 == --output ]]; then output=$2; shift 2; else shift; fi
done
mkdir -p "$output"
printf '%s\n' 'urllib3.exceptions.MaxRetryError: requests.exceptions.SSLError: certificate verify failed' > "$output/plot_ALL_planets.log"
exit 1
"""
        )

        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertEqual((root / "calls").read_text().strip(), "1")
        self.assertFalse(output.exists())
        self.assertTrue(Path(f"{output}-failed-attempt-1").is_dir())

    def test_success_without_output_is_an_operational_failure(self):
        root, output, completed = self.run_launcher(
            """#!/usr/bin/env bash
exit 0
"""
        )

        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertEqual((root / "calls").exists(), False)
        self.assertFalse(output.exists())
        self.assertIn("exited successfully without output", completed.stdout)


if __name__ == "__main__":
    unittest.main()
