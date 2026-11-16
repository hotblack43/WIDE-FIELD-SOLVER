"""Public v25 operator workflow documentation and CI assertions."""
from pathlib import Path
import json
import tomllib
import unittest


ROOT = Path(__file__).resolve().parent


class V25DocumentationTests(unittest.TestCase):
    def test_v25_readme_leads_with_real_commands_before_demo(self):
        text = (ROOT / "v25/README.md").read_text(encoding="utf-8")
        operator = text.index("./go_visible_sky_v25.sh")
        solve = text.index("./go25.sh")
        mmto = text.index("./go_mmto_photometry_v25.sh")
        demo = text.index("./v25/demo.sh")
        self.assertLess(operator, demo)
        self.assertLess(solve, demo)
        self.assertLess(mmto, demo)
        self.assertIn("visible_sky_operator.example.toml", text)
        self.assertIn("propose", text)
        self.assertIn("approve", text)
        self.assertIn("activate", text)
        self.assertIn("./go_visible_sky_v25.sh\n", text)
        self.assertIn("./go_visible_sky_v25.sh auto", text)
        self.assertLess(
            text.index("./go_visible_sky_v25.sh\n"),
            text.index("./go_visible_sky_v25.sh auto"),
        )
        self.assertLess(
            text.index("./go_visible_sky_v25.sh auto"),
            text.index("./go_visible_sky_v25.sh propose"),
        )

    def test_v25_readme_documents_fixed_automatic_gates_and_provenance(self):
        text = (ROOT / "v25/README.md").read_text(encoding="utf-8")
        for phrase in (
            "10 distinct observing dates",
            "8 calibration dates",
            "2 held-out dates",
            "20 held-out originals",
            "100 held-out unmasked detections",
            "0.10 and 0.95",
            "median held-out image-footprint IoU",
            "minimum held-out image-footprint IoU",
            "boundary-intersection fraction",
            "five date-fold",
            "10 pixels",
            "24 pixels",
            "automated validation is not visual review",
            "--replace-active",
            "advanced recovery tools",
        ):
            self.assertIn(phrase, text)
        self.assertIn("another physical camera", text)

    def test_example_toml_keeps_exact_schema_and_leads_with_auto(self):
        path = ROOT / "v25/examples/visible_sky_operator.example.toml"
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(payload),
            {
                "schema", "source_id", "camera_id", "installation_id",
                "orientation", "download_manifest", "archive_root",
                "review_root", "calibration_root",
            },
        )
        self.assertIn("go_visible_sky_v25.sh auto --config", path.read_text())

    def test_v25_readme_records_v24_inheritance_and_cumulative_tables(self):
        text = (ROOT / "v25/README.md").read_text(encoding="utf-8")
        self.assertIn("mmto-v24-backfill-state.json", text)
        self.assertIn("v23 or v24 solver receipt", text)
        self.assertIn("v21, v23, v24, and v25 FITS-header observation tables", text)
        handoff = (ROOT / "v25/HANDOFF.md").read_text(encoding="utf-8")
        self.assertIn("mmto-v24-backfill-state.json", handoff)
        self.assertIn("v23 or v24 receipt", handoff)
        self.assertIn("approved MMTO installation mask", handoff)

    def test_root_status_freezes_v24_and_names_v25_as_active(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        status = (ROOT / "docs/FEATURE_STATUS.md").read_text(encoding="utf-8")
        versions = (ROOT / "docs/VERSIONS.md").read_text(encoding="utf-8")
        for text in (readme, status, versions):
            self.assertIn("v0.25.0", text)
            self.assertIn("go_visible_sky_v25.sh", text)
        self.assertIn("V24 is frozen", status)
        self.assertIn("V25 is the active", status)
        self.assertIn("`go24.sh` | Frozen", versions)
        self.assertIn("`go25.sh` | Active development", versions)

    def test_v25_manifest_contains_operator_and_uses_v24_parent(self):
        manifest = json.loads((ROOT / "v25/SOURCE_MANIFEST.json").read_text())
        self.assertEqual(manifest["version"], "0.25.0")
        self.assertEqual(manifest["based_on_version"], "0.24.0")
        self.assertEqual(manifest["parent_snapshot"], "../docs/v24-runtime.json")
        self.assertIn("visible_sky_operator.py", manifest["sha256"])
        self.assertIn("test_visible_sky_operator.py", manifest["sha256"])
        self.assertIn(
            "examples/visible_sky_operator.example.toml", manifest["sha256"]
        )
        self.assertIn("visible_sky_auto_workflow.py", manifest["sha256"])
        self.assertIn("visible_sky_automatic.py", manifest["sha256"])
        self.assertIn("test_visible_sky_auto_workflow.py", manifest["sha256"])

    def test_ci_runs_v25_operator_and_boundary_checks(self):
        text = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
        self.assertIn("v25-operator", text)
        self.assertIn("test_visible_sky_operator", text)
        self.assertIn("test_visible_sky_auto_workflow", text)
        self.assertIn("test_visible_sky_automatic", text)
        self.assertIn("test_v25_runtime_boundary", text)
        self.assertIn("./v25/demo.sh", text)


if __name__ == "__main__":
    unittest.main()
