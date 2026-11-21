"""Documentation assertions for the v26 development boundary."""
from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parent


class V26DocumentationTests(unittest.TestCase):
    def test_v26_is_development_based_on_frozen_v25(self):
        readme = (ROOT / "v26/README.md").read_text(encoding="utf-8")
        status = (ROOT / "docs/FEATURE_STATUS.md").read_text(encoding="utf-8")
        versions = (ROOT / "docs/VERSIONS.md").read_text(encoding="utf-8")
        self.assertIn("v0.26.0 development runtime", readme)
        self.assertIn("based directly on frozen v25", readme)
        self.assertIn("V26 development line", status)
        self.assertIn("`go26.sh` | Development", versions)
        self.assertIn("Latest packaged release; frozen", versions)

    def test_v26_commands_name_only_v26_runtime(self):
        readme = (ROOT / "v26/README.md").read_text(encoding="utf-8")
        self.assertIn("./go26.sh /full/path/to/image.fits", readme)
        self.assertIn("./go_mmto_photometry_v26.sh", readme)
        self.assertIn("./go_visible_sky_v26.sh", readme)
        self.assertNotIn("./go25.sh", readme)

    def test_saturated_evidence_policy_is_explicit_and_bounded(self):
        readme = (ROOT / "v26/README.md").read_text(encoding="utf-8")
        goal = (ROOT / "v26/GOAL.md").read_text(encoding="utf-8")
        status = (ROOT / "docs/FEATURE_STATUS.md").read_text(encoding="utf-8")
        for text in (readme, goal, status):
            normalised = " ".join(text.split())
            self.assertIn("lower bound", normalised)
            self.assertIn("zenith/extinction", normalised)
        self.assertIn("one-sided magnitude residual", readme)
        self.assertIn("cannot turn a single-planet alias", " ".join(readme.split()))
        self.assertIn("accepted unsaturated-wing model estimates", goal)

    def test_manifest_uses_v25_parent_and_records_development_status(self):
        manifest = json.loads((ROOT / "v26/SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.26.0")
        self.assertEqual(manifest["based_on_version"], "0.25.1")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v25-runtime.json")
        self.assertEqual(manifest["release_status"], "development")
        self.assertIn("point_star_photometric_evidence.py", manifest["sha256"])
        self.assertIn("test_photometric_evidence.py", manifest["sha256"])

    def test_v25_runtime_remains_separate(self):
        self.assertTrue((ROOT / "docs/v25-runtime.json").is_file())
        self.assertTrue((ROOT / "go25.sh").is_file())
        self.assertTrue((ROOT / "go26.sh").is_file())
        self.assertTrue((ROOT / "v25").is_dir())
        self.assertTrue((ROOT / "v26").is_dir())


if __name__ == "__main__":
    unittest.main()
