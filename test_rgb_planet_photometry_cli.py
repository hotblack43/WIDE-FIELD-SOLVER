"""The combined RGB planet-photometry command remains callable."""
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent


class RGBPlanetPhotometryCliTests(unittest.TestCase):
    def test_v23_through_v25_accept_combined_rgb_channel(self):
        for version in ("v23", "v24", "v25"):
            with self.subTest(version=version):
                script = ROOT / version / "scripts" / "plot_planet_photometry.py"
                completed = subprocess.run(
                    [sys.executable, script, "--channel", "RGB", "--help"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("--channel {R,G,B,RGB}", completed.stdout)


if __name__ == "__main__":
    unittest.main()
