"""Sealed cold-start visible-sky replay tests."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from astropy.io import fits

from scripts.replay_visible_sky_cold_start import (
    _classify_mask_supports,
    archive_detector_signature,
    build_parser,
    comparison_metrics,
    create_proposal_seal,
    verify_proposal_seal,
)
from visible_sky_calibration import detector_signature


class ColdStartReplayTests(unittest.TestCase):
    def test_detection_support_audit_distinguishes_visible_boundary_and_excluded(self):
        proposal = np.zeros((20, 30), dtype=bool)
        proposal[:, :15] = True
        detections = [
            {"detection_id": 1, "x_px": 5.0, "y_px": 10.0, "measurement_half_window_px": 2},
            {"detection_id": 2, "x_px": 14.0, "y_px": 10.0, "measurement_half_window_px": 2},
            {"detection_id": 3, "x_px": 24.0, "y_px": 10.0, "measurement_half_window_px": 2},
        ]
        statuses = [
            row["mask_status"]
            for row in _classify_mask_supports(detections, proposal)
        ]
        self.assertEqual(statuses, [
            "accepted_visible_support",
            "rejected_boundary_intersection",
            "rejected_excluded_support",
        ])
    def test_header_signature_matches_native_loader_for_fits(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.fits"
            hdu = fits.PrimaryHDU(np.zeros((3, 20, 24), dtype=np.uint16))
            hdu.header["INSTRUME"] = "CAMERA-A (1234)"
            hdu.writeto(path)
            self.assertEqual(
                archive_detector_signature(path, orientation="native"),
                detector_signature(path, orientation="native"),
            )

    def test_propose_parser_has_no_approved_reference_and_requires_new_output(self):
        parser = build_parser()
        argv = [
            "propose",
            "--download-manifest", "/tmp/manifest.sqlite",
            "--archive-root", "/tmp/archive",
            "--source", "mmto",
            "--camera", "mmto-skycam",
            "--installation-id", "cold-start-a",
            "--orientation", "native",
            "--output", "/tmp/output",
        ]
        args = parser.parse_args(argv)
        self.assertEqual(args.command, "propose")
        with self.assertRaises(SystemExit):
            parser.parse_args([*argv, "--approved-reference-manifest", "/secret.json"])

    def test_seal_inventories_every_pre_evaluation_artifact_and_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.joinpath("selection.json").write_text("{}\n")
            root.joinpath("date-split.json").write_text("{}\n")
            root.joinpath("boundary_review.png").write_bytes(b"normal")
            seal_path = create_proposal_seal(root)
            payload = json.loads(seal_path.read_text())
            self.assertEqual(
                set(payload["artifacts"]),
                {"selection.json", "date-split.json", "boundary_review.png"},
            )
            verify_proposal_seal(seal_path)
            root.joinpath("boundary_review.png").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verify_proposal_seal(seal_path)

    def test_comparison_metrics_are_exact(self):
        proposed = np.array(
            [[True, True, False], [True, False, False]], dtype=bool
        )
        approved = np.array(
            [[True, False, False], [True, True, False]], dtype=bool
        )
        metrics = comparison_metrics(proposed, approved)
        self.assertEqual(metrics["pixels"], 6)
        self.assertEqual(metrics["matching_pixels"], 4)
        self.assertEqual(metrics["false_visible_pixels"], 1)
        self.assertEqual(metrics["false_excluded_pixels"], 1)
        self.assertAlmostEqual(metrics["exact_pixel_agreement"], 4 / 6)
        self.assertAlmostEqual(metrics["intersection_over_union"], 2 / 4)
        self.assertGreaterEqual(metrics["boundary_distance_mean_pixels"], 0.0)


if __name__ == "__main__":
    unittest.main()
