"""Public-facing licence and documentation checks for v0.11.0."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class V11ReleaseDocumentationTests(unittest.TestCase):
    def test_software_license_and_authors_are_explicit(self):
        license_text = (ROOT/"v11/LICENSE").read_text()
        readme = (ROOT/"v11/README.md").read_text()
        self.assertIn("BSD 3-Clause", readme)
        self.assertIn("Peter Thejll and Chris Flynn", license_text)

    def test_mmto_credit_and_rights_boundary_are_explicit(self):
        notice = (ROOT/"v11/NOTICE.md").read_text()
        self.assertIn("MMTO all-sky-camera image courtesy of MMT Observatory", notice)
        self.assertIn("provided with permission from Tim Pickering", notice)
        self.assertIn("does not license the MMTO observation", notice)

    def test_readme_uses_only_standalone_v11_commands(self):
        readme = (ROOT/"v11/README.md").read_text()
        for heading in (
            "## Overview",
            "## Quick start",
            "## Built-in MMTO example",
            "## Solve your own image",
            "## Outputs",
            "## Scientific interpretation",
            "## Supported inputs",
            "## Licence and citation",
            "## Data and image credits",
            "## Known limitations",
        ):
            self.assertIn(heading, readme)
        self.assertIn("requires Bash", readme)
        self.assertIn("`--offline`", readme)
        self.assertIn("./demo.sh --output results/mmto-demo", readme)
        self.assertIn("./go11.sh /full/path/to/image.fits.bz2", readme)
        self.assertNotIn("./go10.sh", readme)
        self.assertNotIn("v10/", readme)

    def test_restricted_photographs_are_not_presented_as_bundled(self):
        combined = (
            (ROOT/"v11/README.md").read_text()
            + (ROOT/"v11/NOTICE.md").read_text()
        )
        self.assertIn("Fred Espenak", combined)
        self.assertIn("not included", combined)

    def test_release_notes_name_curated_assets_and_scientific_boundary(self):
        notes = (ROOT/"docs/RELEASE_v0.11.0.md").read_text()
        for name in (
            "wide-field-solver-v0.11.0.tar.gz",
            "wide-field-solver-v0.11.0.zip",
            "SHA256SUMS",
        ):
            self.assertIn(name, notes)
        self.assertIn("automatic “Source code”", notes)
        self.assertIn("metadata-conditioned", notes)
        self.assertIn("provided with permission from Tim Pickering", notes)

    def test_release_notes_require_one_archive_not_both(self):
        notes = (ROOT/"docs/RELEASE_v0.11.0.md").read_text()
        self.assertIn("Choose one archive", notes)
        self.assertIn("Verification is optional", notes)
        self.assertNotIn("Download these three named release assets", notes)
        self.assertNotIn("sha256sum -c SHA256SUMS\n", notes)
        self.assertIn(
            "grep 'wide-field-solver-v0.11.0.tar.gz$' SHA256SUMS | sha256sum -c -",
            notes,
        )
        self.assertIn(
            "grep 'wide-field-solver-v0.11.0.zip$' SHA256SUMS | sha256sum -c -",
            notes,
        )


if __name__ == "__main__":
    unittest.main()
