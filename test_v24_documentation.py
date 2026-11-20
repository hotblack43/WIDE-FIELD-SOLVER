"""Public v24 calibration workflow documentation and CI assertions."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class V24DocumentationTests(unittest.TestCase):
    def test_public_status_records_visual_acceptance_and_fixed_limits(self):
        readme = (ROOT / "v24/README.md").read_text(encoding="utf-8")
        status = (ROOT / "docs/FEATURE_STATUS.md").read_text(encoding="utf-8")
        for text in (readme, status):
            self.assertIn("visually accepted", text)
            self.assertIn("0.98", text)
            self.assertIn("0.97", text)
            self.assertIn("must not be relaxed", text)
            self.assertIn("check-acceptance", text)
        self.assertIn("cold_start_candidate_mask.png", readme)

    def test_v24_readme_names_current_launcher_and_complete_lifecycle(self):
        text = (ROOT / "v24/README.md").read_text(encoding="utf-8")
        self.assertIn("./go24.sh", text)
        self.assertNotIn("./go23.sh", text)
        for phrase in (
            "draft_not_approved",
            "propose",
            "revise",
            "approve",
            "activate",
            "assign-existing",
            "--calibration-registry",
            "--installation-assignments",
            "--allow-unconfigured-visible-sky",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_public_status_does_not_claim_non_mmto_validation(self):
        status = (ROOT / "docs/FEATURE_STATUS.md").read_text(encoding="utf-8")
        self.assertIn("generic calibration machinery", status)
        self.assertIn("not yet validated on a real non-MMTO camera", status)
        self.assertIn("3,194", status)
        self.assertIn("98.418", status)

    def test_root_and_version_guide_identify_v24_as_frozen_parent(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        versions = (ROOT / "docs/VERSIONS.md").read_text(encoding="utf-8")
        self.assertIn("./go25.sh", readme)
        self.assertIn("frozen v24", readme)
        self.assertIn("go24.sh", versions)
        self.assertIn("v0.24.0", versions)
        self.assertIn("v0.25.1", versions)
        self.assertIn("frozen", versions)
        self.assertIn("Latest packaged release", versions)

    def test_ci_retains_baselines_and_adds_v24_calibration_job(self):
        workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        self.assertIn('solver: [".", "v4", "v5"]', workflow)
        self.assertIn("v24-calibration", workflow)
        self.assertIn("test_visible_sky_cold_start", workflow)
        self.assertIn("tests.test_allsky_manifest tests.test_allsky_cli", workflow)
        self.assertIn("./v24/demo.sh", workflow)


if __name__ == "__main__":
    unittest.main()
