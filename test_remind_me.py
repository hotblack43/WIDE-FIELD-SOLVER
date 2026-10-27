"""The plot reminder must keep useful pointers after a late stage fails."""
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parent / "remind_me.sh"


class RemindMeTests(unittest.TestCase):
    def test_latest_run_and_explicit_older_fallbacks(self):
        with tempfile.TemporaryDirectory() as temporary:
            runs = Path(temporary)
            old = runs / "v23-20261025T120000Z"
            new = runs / "v23-20261026T050000Z"
            (old / "planet-empirical-extinction").mkdir(parents=True)
            (new / "planet-photometry").mkdir(parents=True)
            (old / "planet-empirical-extinction" / "airmass.pdf").write_bytes(b"%PDF-old")
            (old / "planet-photometry").mkdir()
            (old / "planet-photometry" / "time.pdf").write_bytes(b"%PDF-stale")
            (new / "planet-photometry" / "time.pdf").write_bytes(b"%PDF-new")
            (new / "acquisition_timeline.pdf").write_bytes(b"%PDF-acquisition")
            (new / "pipeline_summary.json").write_text(
                '{"status":"operational_failed","processing":'
                '{"attempted":50,"succeeded":13,"solver_failed":37}}'
            )

            result = subprocess.run(
                [str(SCRIPT), "--runs-dir", str(runs)],
                cwd="/tmp", text=True, capture_output=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("operational_failed", result.stdout)
            self.assertIn("50 attempted", result.stdout)
            self.assertIn(str(new / "acquisition_timeline.pdf"), result.stdout)
            self.assertIn(str(new / "planet-photometry" / "time.pdf"), result.stdout)
            self.assertIn(str(old / "planet-empirical-extinction" / "airmass.pdf"), result.stdout)
            self.assertNotIn(str(old / "planet-photometry" / "time.pdf"), result.stdout)
            self.assertIn("earlier run", result.stdout)


if __name__ == "__main__":
    unittest.main()
