"""Regression tests for fail-closed automatic visible-sky acceptance."""
from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from visible_sky_automatic import (
    AUTOMATIC_ACCEPTANCE_SCHEMA,
    AUTOMATIC_ACCEPTANCE_THRESHOLDS,
    atomic_write_json,
    automatic_mask_id,
    canonical_acceptance_payload,
    canonical_json_sha256,
    evaluate_automatic_gates,
    validate_automatic_acceptance,
)


PASSING_METRICS = {
    "total_date_count": 10,
    "calibration_date_count": 8,
    "held_out_date_count": 2,
    "held_out_source_count": 20,
    "detector_signature_count": 1,
    "proposal_visible_pixel_count": 1,
    "proposal_pixel_count": 10,
    "proposal_connected_component_count": 1,
    "finalized_visible_pixel_count": 1,
    "finalized_pixel_count": 10,
    "finalized_connected_component_count": 1,
    "held_out_footprint_iou_median_numerator": 80,
    "held_out_footprint_iou_median_denominator": 100,
    "held_out_footprint_iou_minimum_numerator": 50,
    "held_out_footprint_iou_minimum_denominator": 100,
    "held_out_unmasked_detection_count": 100,
    "held_out_boundary_intersection_count": 5,
}

PASSING_FOLDS = tuple(
    {
        "fold_index": index,
        "mask_intersection_count": 95,
        "mask_union_count": 100,
        "boundary_distance_mean_pixels": 10.0,
        "boundary_distance_p95_pixels": 24.0,
    }
    for index in range(5)
)


class AutomaticGateTests(unittest.TestCase):
    def test_exact_fixed_thresholds_pass_at_boundaries(self) -> None:
        self.assertEqual(AUTOMATIC_ACCEPTANCE_SCHEMA, "visible-sky-automatic-v1")
        self.assertEqual(
            dict(AUTOMATIC_ACCEPTANCE_THRESHOLDS),
            {
                "total_date_count_minimum": 10,
                "calibration_date_count_minimum": 8,
                "held_out_date_count_minimum": 2,
                "held_out_source_count_minimum": 20,
                "detector_signature_count_exact": 1,
                "proposal_visible_fraction_minimum": 0.10,
                "proposal_visible_fraction_maximum": 0.95,
                "proposal_connected_component_count_exact": 1,
                "finalized_visible_fraction_minimum": 0.10,
                "finalized_visible_fraction_maximum": 0.95,
                "finalized_connected_component_count_exact": 1,
                "held_out_footprint_iou_median_minimum": 0.80,
                "held_out_footprint_iou_minimum_minimum": 0.50,
                "held_out_unmasked_detection_count_minimum": 100,
                "held_out_boundary_intersection_fraction_maximum": 0.05,
                "fold_count_exact": 5,
                "fold_mask_iou_minimum": 0.95,
                "fold_boundary_distance_mean_pixels_maximum": 10.0,
                "fold_boundary_distance_p95_pixels_maximum": 24.0,
            },
        )

        result = evaluate_automatic_gates(PASSING_METRICS, PASSING_FOLDS)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["failed_gates"], [])
        fold_rows = [
            row
            for row in result["checks"]
            if row["gate"].startswith("fold_") and row["gate"] != "fold_count_exact"
        ]
        self.assertEqual(len(fold_rows), 15)
        fractions = {
            row["gate"]: row
            for row in result["checks"]
            if "fraction" in row["gate"] or "iou" in row["gate"]
        }
        self.assertEqual(
            (fractions["proposal_visible_fraction_minimum"]["numerator"],
             fractions["proposal_visible_fraction_minimum"]["denominator"]),
            (1, 10),
        )
        self.assertEqual(
            (fractions["held_out_boundary_intersection_fraction_maximum"]["numerator"],
             fractions["held_out_boundary_intersection_fraction_maximum"]["denominator"]),
            (5, 100),
        )
        self.assertEqual(
            (fractions["fold_0_mask_iou_minimum"]["numerator"],
             fractions["fold_0_mask_iou_minimum"]["denominator"]),
            (95, 100),
        )

    def test_each_gate_fails_independently(self) -> None:
        mutations = (
            ("total_date_count_minimum", "total_date_count", 9),
            ("calibration_date_count_minimum", "calibration_date_count", 7),
            ("held_out_date_count_minimum", "held_out_date_count", 1),
            ("held_out_source_count_minimum", "held_out_source_count", 19),
            ("detector_signature_count_exact", "detector_signature_count", 2),
            ("proposal_visible_fraction_minimum", "proposal_visible_pixel_count", 0),
            ("proposal_visible_fraction_maximum", "proposal_visible_pixel_count", 10),
            ("proposal_connected_component_count_exact", "proposal_connected_component_count", 2),
            ("finalized_visible_fraction_minimum", "finalized_visible_pixel_count", 0),
            ("finalized_visible_fraction_maximum", "finalized_visible_pixel_count", 10),
            ("finalized_connected_component_count_exact", "finalized_connected_component_count", 0),
            ("held_out_footprint_iou_median_minimum", "held_out_footprint_iou_median_numerator", 79),
            ("held_out_footprint_iou_minimum_minimum", "held_out_footprint_iou_minimum_numerator", 49),
            ("held_out_unmasked_detection_count_minimum", "held_out_unmasked_detection_count", 99),
            ("held_out_boundary_intersection_fraction_maximum", "held_out_boundary_intersection_count", 6),
        )
        for gate, key, value in mutations:
            with self.subTest(gate=gate):
                metrics = dict(PASSING_METRICS)
                metrics[key] = value
                if gate == "held_out_unmasked_detection_count_minimum":
                    metrics["held_out_boundary_intersection_count"] = 4
                result = evaluate_automatic_gates(metrics, PASSING_FOLDS)
                self.assertEqual(result["failed_gates"], [gate])

        fold_mutations = (
            ("fold_2_mask_iou_minimum", "mask_intersection_count", 94),
            ("fold_2_boundary_distance_mean_pixels_maximum", "boundary_distance_mean_pixels", 10.01),
            ("fold_2_boundary_distance_p95_pixels_maximum", "boundary_distance_p95_pixels", 24.01),
        )
        for gate, key, value in fold_mutations:
            with self.subTest(gate=gate):
                folds = [dict(row) for row in PASSING_FOLDS]
                folds[2][key] = value
                result = evaluate_automatic_gates(PASSING_METRICS, folds)
                self.assertEqual(result["failed_gates"], [gate])

    def test_boolean_missing_nonfinite_and_zero_denominator_values_fail_closed(self) -> None:
        cases = (
            ("invalid_total_date_count", {**PASSING_METRICS, "total_date_count": True}, PASSING_FOLDS),
            ("missing_total_date_count", {key: value for key, value in PASSING_METRICS.items() if key != "total_date_count"}, PASSING_FOLDS),
            ("invalid_proposal_pixel_count", {**PASSING_METRICS, "proposal_pixel_count": 0}, PASSING_FOLDS),
            ("invalid_held_out_footprint_iou_median_numerator", {**PASSING_METRICS, "held_out_footprint_iou_median_numerator": math.nan}, PASSING_FOLDS),
            ("invalid_held_out_footprint_iou_minimum_denominator", {**PASSING_METRICS, "held_out_footprint_iou_minimum_denominator": 0}, PASSING_FOLDS),
        )
        for failed_gate, metrics, folds in cases:
            with self.subTest(failed_gate=failed_gate):
                result = evaluate_automatic_gates(metrics, folds)
                self.assertEqual(result["status"], "fail")
                self.assertIn(failed_gate, result["failed_gates"])

        folds = [dict(row) for row in PASSING_FOLDS]
        folds[3]["boundary_distance_mean_pixels"] = math.inf
        result = evaluate_automatic_gates(PASSING_METRICS, folds)
        self.assertEqual(result["failed_gates"], ["invalid_fold_3_boundary_distance_mean_pixels"])

        result = evaluate_automatic_gates(PASSING_METRICS, PASSING_FOLDS[:4])
        self.assertEqual(result["failed_gates"], ["fold_count_exact"])


class AutomaticIdentityTests(unittest.TestCase):
    def _payload(self, path: str, timestamp: str) -> dict[str, object]:
        return canonical_acceptance_payload(
            identity={
                "source_id": "camera-archive",
                "camera_id": "camera-1",
                "installation_id": "roof-north",
                "orientation": "native",
                "detector_signature_sha256": "1" * 64,
                "run_path": path,
                "created_utc": timestamp,
            },
            sources=(
                {"source_sha256": "b" * 64, "observed_bytes": 20, "path": path, "observed_utc": timestamp},
                {"source_sha256": "a" * 64, "observed_bytes": 10, "path": path + "/two", "observed_utc": timestamp},
            ),
            metrics=PASSING_METRICS,
            fold_metrics=PASSING_FOLDS,
            artifact_sha256={"z.png": "f" * 64, "a.json": "e" * 64},
            code_sha256={"visible_sky_automatic.py": "d" * 64},
            finalized_mask_sha256="c" * 64,
        )

    def test_acceptance_payload_is_path_and_time_independent(self) -> None:
        first = self._payload("/tmp/run-one", "2026-11-16T01:02:03Z")
        second = self._payload("/srv/other/run", "2099-01-01T00:00:00Z")
        self.assertEqual(first, second)
        encoded = json.dumps(first)
        self.assertNotIn("/tmp", encoded)
        self.assertNotIn("/srv", encoded)
        self.assertNotIn("2026-", encoded)
        self.assertNotIn("2099-", encoded)

    def test_canonical_hash_is_order_independent(self) -> None:
        left = {"outer": {"z": 2, "a": 1}, "rows": [{"b": 2, "a": 1}]}
        right = {"rows": [{"a": 1, "b": 2}], "outer": {"a": 1, "z": 2}}
        self.assertEqual(canonical_json_sha256(left), canonical_json_sha256(right))
        self.assertEqual(len(canonical_json_sha256(left)), 64)

    def test_mask_id_binds_mask_and_acceptance_hashes(self) -> None:
        mask_id = automatic_mask_id("roof-north", "a" * 64, "b" * 64)
        self.assertEqual(mask_id, "roof-north-auto-aaaaaaaaaaaa-bbbbbbbbbbbb")
        self.assertNotEqual(mask_id, automatic_mask_id("roof-north", "c" * 64, "b" * 64))
        self.assertNotEqual(mask_id, automatic_mask_id("roof-north", "a" * 64, "d" * 64))
        for invalid in ("../roof", "roof north", "", "/absolute"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                automatic_mask_id(invalid, "a" * 64, "b" * 64)
        with self.assertRaises(ValueError):
            automatic_mask_id("roof", "A" * 64, "b" * 64)

    def test_acceptance_validator_rejects_minimal_or_semantically_changed_json(self) -> None:
        payload = self._payload("/tmp/run", "2026-11-16T00:00:00Z")
        self.assertEqual(validate_automatic_acceptance(payload), payload)
        with self.assertRaisesRegex(ValueError, "invalid automatic acceptance"):
            validate_automatic_acceptance(
                {"schema": AUTOMATIC_ACCEPTANCE_SCHEMA, "status": "pass"}
            )
        changed = json.loads(json.dumps(payload))
        changed["identity"]["camera_id"] = "other-camera"
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            validate_automatic_acceptance(
                changed, expected_identity={"camera_id": "camera-1"}
            )

    def test_atomic_json_never_leaves_partial_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "receipt.json"
            destination.write_text('{"old":true}\n', encoding="utf-8")
            with mock.patch("visible_sky_automatic.os.replace", side_effect=OSError("stop")):
                with self.assertRaisesRegex(OSError, "stop"):
                    atomic_write_json(destination, {"new": True})
            self.assertEqual(destination.read_text(encoding="utf-8"), '{"old":true}\n')
            self.assertEqual(list(destination.parent.glob(".receipt.json.*.tmp")), [])

            atomic_write_json(destination, {"new": True})
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), {"new": True})


if __name__ == "__main__":
    unittest.main()
