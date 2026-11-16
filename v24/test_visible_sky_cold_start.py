"""Sealed cold-start visible-sky replay tests."""
from __future__ import annotations

import json
import io
import hashlib
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout

import numpy as np
from astropy.io import fits
from PIL import Image

from scripts.replay_visible_sky_cold_start import (
    _classify_mask_supports,
    archive_detector_signature,
    build_parser,
    check_regression_acceptance,
    comparison_metrics,
    create_proposal_seal,
    main,
    verify_proposal_seal,
)
from visible_sky_calibration import detector_signature


class ColdStartReplayTests(unittest.TestCase):
    @staticmethod
    def _acceptance_receipt():
        receipt_path = (
            Path(__file__).parent
            / "examples/mmto/cold_start_regression_acceptance.json"
        )
        return json.loads(receipt_path.read_text(encoding="utf-8"))

    @staticmethod
    def _accepted_comparison(metrics):
        return {
            "status": "evaluated_after_sealed_cold_start",
            "proposal_seal_sha256": (
                "08207d2758c02138c5d5c590fb29255f883f58461177a7b1b38fe025fde03423"
            ),
            "approved_reference_mask_id": "mmto-visible-sky-2026a-v1",
            "approved_reference_manifest_sha256": (
                "383dd5f2f212f1035d71612970a3456496c3c4f4c11ad3edacea6e3b37f4f904"
            ),
            "approved_reference_mask_sha256": (
                "996e27f13cb726c8b759fca641c05b7937325ebd81e297db2f06de17f48cd144"
            ),
            "metrics": metrics,
        }

    @classmethod
    def _sealed_comparison(cls, metrics, temporary):
        seal_root = Path(temporary) / "sealed-candidate"
        seal_root.mkdir()
        source = (
            Path(__file__).parent
            / "examples/mmto/cold_start_candidate_mask.png"
        )
        seal_root.joinpath("cold_start_candidate_mask.png").write_bytes(
            source.read_bytes()
        )
        seal_path = create_proposal_seal(seal_root)
        comparison = cls._accepted_comparison(metrics)
        comparison["proposal_seal"] = str(seal_path)
        comparison["proposal_seal_sha256"] = hashlib.sha256(
            seal_path.read_bytes()
        ).hexdigest()
        return comparison

    def test_peter_approved_sealed_mmto_result_fixes_conservative_limits(self):
        receipt = self._acceptance_receipt()
        candidate = np.asarray(Image.open(
            Path(__file__).parent
            / "examples/mmto/cold_start_candidate_mask.png"
        ).convert("L")) == 255
        approved = np.asarray(Image.open(
            Path(__file__).parent
            / "data/sky_masks/mmto_installation_2026a.png"
        ).convert("L")) == 255
        with tempfile.TemporaryDirectory() as temporary:
            comparison = self._sealed_comparison(
                comparison_metrics(candidate, approved), temporary
            )
            result = check_regression_acceptance(comparison, receipt)
            self.assertEqual(result["status"], "pass")
            self.assertEqual(receipt["visual_review"]["decision"], "accepted")
            self.assertEqual(receipt["visual_review"]["reviewed_by"], "Peter Thejll")
            self.assertEqual(receipt["thresholds"], {
                "exact_pixel_agreement": {"minimum": 0.98},
                "intersection_over_union": {"minimum": 0.97},
                "false_visible_fraction": {"maximum": 0.015},
                "false_excluded_fraction": {"maximum": 0.005},
                "boundary_distance_mean_pixels": {"maximum": 6.5},
                "boundary_distance_p95_pixels": {"maximum": 16.0},
            })
            comparison_path = Path(temporary) / "comparison.json"
            comparison_path.write_text(
                json.dumps(comparison, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                status = main([
                    "check-acceptance",
                    "--comparison", str(comparison_path),
                ])
        self.assertEqual(status, 0)

    def test_regression_acceptance_rejects_seal_mismatch_and_each_failed_limit(self):
        receipt = self._acceptance_receipt()
        with tempfile.TemporaryDirectory() as temporary:
            comparison = self._sealed_comparison(
                receipt["observed_metrics"], temporary
            )
            wrong_seal = json.loads(json.dumps(receipt))
            wrong_seal["proposal_seal_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "proposal seal"):
                check_regression_acceptance(comparison, wrong_seal)
            missing_candidate_seal = json.loads(json.dumps(comparison))
            missing_candidate_seal.pop("proposal_seal_sha256")
            with self.assertRaisesRegex(ValueError, "proposal seal"):
                check_regression_acceptance(missing_candidate_seal, receipt)

            for metric, rule in receipt["thresholds"].items():
                with self.subTest(metric=metric):
                    failed = json.loads(json.dumps(comparison))
                    if "minimum" in rule:
                        failed["metrics"][metric] = rule["minimum"] - 1e-6
                    else:
                        failed["metrics"][metric] = rule["maximum"] + 1e-6
                    result = check_regression_acceptance(failed, receipt)
                    self.assertEqual(result["status"], "fail")
                    self.assertEqual(result["failed_metrics"], [metric])

    def test_regression_acceptance_rejects_weakened_or_altered_receipt(self):
        receipt = self._acceptance_receipt()
        with tempfile.TemporaryDirectory() as temporary:
            comparison = self._sealed_comparison(
                receipt["observed_metrics"], temporary
            )
            mutations = []
            omitted = json.loads(json.dumps(receipt))
            omitted["thresholds"].pop("intersection_over_union")
            mutations.append((omitted, "thresholds"))
            relaxed = json.loads(json.dumps(receipt))
            relaxed["thresholds"]["intersection_over_union"]["minimum"] = 0.50
            mutations.append((relaxed, "thresholds"))
            evidence = json.loads(json.dumps(receipt))
            evidence["evidence_sha256"]["comparison.json"] = "0" * 64
            mutations.append((evidence, "evidence"))
            reference = json.loads(json.dumps(receipt))
            reference["approved_reference"]["mask_sha256"] = "0" * 64
            mutations.append((reference, "reference"))
            scope = json.loads(json.dumps(receipt))
            scope["scope"] = "all cameras"
            mutations.append((scope, "scope"))
            for changed, message in mutations:
                with self.subTest(message=message):
                    with self.assertRaisesRegex(ValueError, message):
                        check_regression_acceptance(comparison, changed)

    def test_check_acceptance_command_returns_failure_for_computed_regression(self):
        receipt_path = (
            Path(__file__).parent
            / "examples/mmto/cold_start_regression_acceptance.json"
        )
        receipt = self._acceptance_receipt()
        metrics = dict(receipt["observed_metrics"])
        metrics["intersection_over_union"] = 0.50
        with tempfile.TemporaryDirectory() as temporary:
            comparison = self._sealed_comparison(metrics, temporary)
            comparison_path = Path(temporary) / "comparison.json"
            comparison_path.write_text(
                json.dumps(comparison, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                status = main([
                    "check-acceptance",
                    "--comparison", str(comparison_path),
                    "--acceptance", str(receipt_path),
                ])
        self.assertEqual(status, 1)
        self.assertEqual(
            json.loads(stdout.getvalue())["failed_metrics"],
            ["intersection_over_union"],
        )

    def test_regression_acceptance_rejects_invented_seal_and_boolean_metrics(self):
        receipt = self._acceptance_receipt()
        comparison = self._accepted_comparison(receipt["observed_metrics"])
        comparison["proposal_seal_sha256"] = "f" * 64
        comparison["proposal_seal"] = "/does/not/exist/proposal-seal.json"
        with self.assertRaises((FileNotFoundError, ValueError)):
            check_regression_acceptance(comparison, receipt)

        for metric, value in (
            ("exact_pixel_agreement", True),
            ("false_visible_fraction", False),
        ):
            with self.subTest(metric=metric):
                with tempfile.TemporaryDirectory() as temporary:
                    malformed = self._sealed_comparison(
                        receipt["observed_metrics"], temporary
                    )
                    malformed["metrics"][metric] = value
                    with self.assertRaisesRegex(ValueError, "non-finite regression metric"):
                        check_regression_acceptance(malformed, receipt)

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
