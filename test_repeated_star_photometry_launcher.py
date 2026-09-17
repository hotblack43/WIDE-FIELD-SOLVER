import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "make_repeated_star_photometry_plots.sh"


class RepeatedStarPhotometryLauncherTests(unittest.TestCase):
    def test_launcher_uses_repository_defaults_from_any_working_directory(self):
        self.assertTrue(LAUNCHER.is_file(), "plot launcher is missing")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            capture = temporary / "args.json"
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_uv = fake_bin / "uv"
            fake_uv.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['WFS_CAPTURE']).write_text(json.dumps(sys.argv[1:]))\n"
            )
            fake_uv.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            environment["WFS_CAPTURE"] = str(capture)

            completed = subprocess.run(
                [str(LAUNCHER)], cwd="/tmp", env=environment,
                capture_output=True, text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(
                json.loads(capture.read_text()),
                [
                    "run", "--project", str(ROOT), "--frozen", "python",
                    str(ROOT / "scripts/plot_repeated_apicam_photometry.py"),
                    "--database", str(ROOT / "results/stars.sqlite"),
                    "--gaia-catalogue",
                    str(ROOT / "v7/data/stars_gaia_dr3_g75.gaia-source.csv"),
                    "--output", str(ROOT / "results/apicam-repeated-star-photometry"),
                ],
            )

    def test_launcher_forwards_explicit_overrides(self):
        self.assertTrue(LAUNCHER.is_file(), "plot launcher is missing")
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            capture = temporary / "args.json"
            fake_bin = temporary / "bin"
            fake_bin.mkdir()
            fake_uv = fake_bin / "uv"
            fake_uv.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['WFS_CAPTURE']).write_text(json.dumps(sys.argv[1:]))\n"
            )
            fake_uv.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}:{environment['PATH']}"
            environment["WFS_CAPTURE"] = str(capture)

            completed = subprocess.run(
                [str(LAUNCHER), "--database", "/data/custom.sqlite",
                 "--output", "/plots/custom"],
                cwd="/tmp", env=environment, capture_output=True, text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            arguments = json.loads(capture.read_text())
            self.assertEqual(
                arguments[-4:],
                ["--database", "/data/custom.sqlite", "--output", "/plots/custom"],
            )


if __name__ == "__main__":
    unittest.main()
