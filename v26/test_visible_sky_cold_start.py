"""Sealed cold-start visible-sky replay tests."""
from __future__ import annotations

import json
import io
import hashlib
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from argparse import Namespace
from unittest import mock

import numpy as np
from astropy.io import fits
from PIL import Image

from scripts.replay_visible_sky_cold_start import (
    _classify_mask_supports,
    _held_out_evaluation,
    archive_detector_signature,
    build_parser,
    check_regression_acceptance,
    calibration_date_folds,
    comparison_metrics,
    create_sealed_proposal_from_sources,
    create_proposal_seal,
    main,
    propose_command,
    verify_completed_point_source_audit,
    verify_proposal_seal,
    _point_source_audit,
    _verify_held_out_source,
)
from visible_sky_calibration import CalibrationSource, detector_signature, partition_dates


class ColdStartReplayTests(unittest.TestCase):
    @staticmethod
    def _calibration_sources(root: Path, date_count: int = 10) -> tuple[CalibrationSource, ...]:
        sources = []
        yy, xx = np.indices((48, 64))
        radius = np.hypot(xx - 31.5, yy - 23.5)
        for index in range(date_count):
            date = f"2026-10-{index + 1:02d}"
            pixels = np.where(
                radius < 20 + (index % 2),
                80 + ((3 * xx + 5 * yy + index * 11) % 150),
                4 + index,
            ).astype(np.uint8)
            path = root / f"{date.replace('-', '_')}_120000.png"
            Image.fromarray(pixels, mode="L").save(path)
            data = path.read_bytes()
            sources.append(
                CalibrationSource(
                    path=path,
                    source_sha256=hashlib.sha256(data).hexdigest(),
                    observed_bytes=len(data),
                    source_id="test-source",
                    camera_id="test-camera",
                    observed_utc=f"{date}T12:00:00Z",
                    observation_date=date,
                    remote_url=f"https://example.invalid/{path.name}",
                )
            )
        return tuple(sources)

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

    def test_source_helper_reproduces_cli_proposal_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = self._calibration_sources(root)
            cli_output = root / "cli"
            helper_output = root / "helper"
            args = Namespace(
                output=cli_output,
                download_manifest=root / "unused.sqlite",
                archive_root=root,
                source="test-source",
                camera="test-camera",
                installation_id="test-installation",
                orientation="native",
                holdout_modulus=5,
                holdout_remainder=0,
            )
            with mock.patch(
                "scripts.replay_visible_sky_cold_start.verified_sources_from_manifest",
                return_value=sources,
            ):
                cli_seal = propose_command(args)

            split = partition_dates(sources, holdout_modulus=5, holdout_remainder=0)
            split_payload = json.loads((cli_output / "date-split.json").read_text())
            helper_seal = create_sealed_proposal_from_sources(
                split.selected_calibration_sources,
                output=helper_output,
                source_id="test-source",
                camera_id="test-camera",
                installation_id="test-installation",
                orientation="native",
                date_split_payload=split_payload,
            )

            cli_selection = json.loads((cli_output / "selection.json").read_text())
            helper_selection = json.loads((helper_output / "selection.json").read_text())
            self.assertEqual(
                [row["source_sha256"] for row in cli_selection["selection"]["sources"]],
                [row["source_sha256"] for row in helper_selection["selection"]["sources"]],
            )
            self.assertEqual(cli_selection["detector_signature"], helper_selection["detector_signature"])
            self.assertEqual(cli_selection["proposal"], helper_selection["proposal"])
            self.assertEqual(
                json.loads(cli_seal.read_text())["artifacts"],
                json.loads(helper_seal.read_text())["artifacts"],
            )
            self.assertEqual(
                sorted(path.name for path in cli_output.iterdir()),
                sorted(path.name for path in helper_output.iterdir()),
            )

    def test_primary_cli_still_holds_out_complete_dates_before_pixels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = self._calibration_sources(root)
            split = partition_dates(sources, holdout_modulus=5, holdout_remainder=0)
            loaded = []
            from scripts import replay_visible_sky_cold_start as replay

            original_load = replay.load_native_luminance

            def recording_load(path, **kwargs):
                loaded.append(Path(path))
                return original_load(path, **kwargs)

            args = Namespace(
                output=root / "proposal",
                download_manifest=root / "unused.sqlite",
                archive_root=root,
                source="test-source",
                camera="test-camera",
                installation_id="test-installation",
                orientation="native",
                holdout_modulus=5,
                holdout_remainder=0,
            )
            with mock.patch.object(replay, "verified_sources_from_manifest", return_value=sources), mock.patch.object(
                replay, "load_native_luminance", side_effect=recording_load
            ):
                propose_command(args)
            self.assertEqual(set(loaded), {row.path for row in split.selected_calibration_sources})
            self.assertTrue(set(loaded).isdisjoint({row.path for row in split.holdout_sources}))

    def test_five_folds_are_deterministic_and_omit_disjoint_calibration_dates(self):
        with tempfile.TemporaryDirectory() as temporary:
            sources = list(self._calibration_sources(Path(temporary), date_count=10))
            shuffled = tuple(sources[index] for index in (7, 1, 9, 0, 5, 2, 8, 4, 6, 3))
            first = calibration_date_folds(shuffled)
            second = calibration_date_folds(tuple(reversed(shuffled)))
            self.assertEqual(
                [[row.source_sha256 for row in fold] for fold in first],
                [[row.source_sha256 for row in fold] for fold in second],
            )
            all_dates = {row.observation_date for row in sources}
            omitted = [all_dates - {row.observation_date for row in fold} for fold in first]
            self.assertEqual(len(first), 5)
            self.assertTrue(all(len(dates) == 2 for dates in omitted))
            self.assertEqual(set().union(*omitted), all_dates)
            self.assertEqual(sum(len(dates) for dates in omitted), len(all_dates))

    def test_each_fold_recycles_phase_selection_from_full_date_populations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = []
            for day in range(10):
                date_value = f"2026-10-{day + 1:02d}"
                for frame in range(4):
                    path = root / f"opaque-{day}-{frame}.fits"
                    sources.append(CalibrationSource(
                        path=path,
                        source_sha256=f"{day * 4 + frame:064x}",
                        observed_bytes=100,
                        source_id="test-source",
                        camera_id="test-camera",
                        observed_utc=f"{date_value}T{frame:02d}:00:00Z",
                        observation_date=date_value,
                        remote_url=f"https://example.invalid/{day}/{frame}",
                    ))
            folds = calibration_date_folds(tuple(reversed(sources)))
            for fold in folds:
                by_date = {}
                for source in fold:
                    by_date.setdefault(source.observation_date, []).append(source)
                self.assertTrue(all(len(members) == 1 for members in by_date.values()))
                selected_hours = [
                    int(by_date[date_value][0].observed_utc[11:13])
                    for date_value in sorted(by_date)
                ]
                self.assertEqual(
                    selected_hours,
                    [1, 2, 2] * (len(selected_hours) // 3)
                    + [1, 2, 2][: len(selected_hours) % 3],
                )

    def test_source_helper_uses_manifest_dates_for_opaque_filenames(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            yy, xx = np.indices((48, 64))
            sources = []
            for index in range(3):
                path = root / f"opaque-{index}.png"
                pixels = np.where(np.hypot(xx - 31.5, yy - 23.5) < 20, 180, 4)
                Image.fromarray(pixels.astype(np.uint8), mode="L").save(path)
                data = path.read_bytes()
                date_value = f"2026-10-{index + 1:02d}"
                sources.append(CalibrationSource(
                    path=path,
                    source_sha256=hashlib.sha256(data).hexdigest(),
                    observed_bytes=len(data),
                    source_id="test-source",
                    camera_id="test-camera",
                    observed_utc=f"{date_value}T12:00:00Z",
                    observation_date=date_value,
                    remote_url=f"https://example.invalid/{index}",
                ))
            output = root / "proposal"
            create_sealed_proposal_from_sources(
                tuple(sources),
                output=output,
                source_id="test-source",
                camera_id="test-camera",
                installation_id="test-installation",
                orientation="native",
            )
            selection = json.loads((output / "selection.json").read_text())
            self.assertEqual(
                [row["observation_date"] for row in selection["selection"]["sources"]],
                ["2026-10-01", "2026-10-02", "2026-10-03"],
            )

    def test_held_out_evaluation_uses_manifest_date_for_opaque_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pixels = np.full((48, 64), 180, dtype=np.uint8)
            pixels[:, :8] = 4
            path = root / "opaque-held-out.png"
            Image.fromarray(pixels, mode="L").save(path)
            data = path.read_bytes()
            source_hash = hashlib.sha256(data).hexdigest()
            record = {
                "path": str(path),
                "source_sha256": source_hash,
                "observed_bytes": len(data),
                "source_id": "test-source",
                "camera_id": "test-camera",
                "observed_utc": "2026-10-21T12:00:00Z",
                "observation_date": "2026-10-21",
                "remote_url": "https://example.invalid/opaque-held-out.png",
            }
            (root / "date-split.json").write_text(
                json.dumps({"holdout_sources": [record]}), encoding="utf-8"
            )
            proposal = np.zeros((48, 64), dtype=bool)
            proposal[:, 8:] = True
            from scripts import replay_visible_sky_cold_start as replay

            original_load = replay.load_native_luminance

            def recording_load(source_path, **kwargs):
                self.assertEqual(kwargs["observation_date"], "2026-10-21")
                self.assertEqual(kwargs["source_sha256"], source_hash)
                return original_load(source_path, **kwargs)

            point_summary = {
                "unmasked_detection_count": 0,
                "accepted_visible_support_count": 0,
                "rejected_excluded_support_count": 0,
                "rejected_boundary_intersection_count": 0,
                "visible_sky_sources_rejected": 0,
            }
            with mock.patch.object(
                replay, "load_native_luminance", side_effect=recording_load
            ), mock.patch.object(replay, "_point_source_audit", return_value=point_summary):
                result = _held_out_evaluation(root, proposal)
            self.assertEqual(result["source_count"], 1)

    def test_primary_holdout_dates_never_enter_any_fold(self):
        with tempfile.TemporaryDirectory() as temporary:
            sources = self._calibration_sources(Path(temporary), date_count=12)
            split = partition_dates(sources, holdout_modulus=5, holdout_remainder=0)
            folds = calibration_date_folds(split.calibration_sources)
            holdout = set(split.holdout_dates)
            self.assertTrue(all(holdout.isdisjoint({row.observation_date for row in fold}) for fold in folds))

    def test_too_few_calibration_dates_fail_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = self._calibration_sources(root, date_count=4)
            output = root / "folds"
            with self.assertRaisesRegex(ValueError, "five calibration dates"):
                calibration_date_folds(sources)
            self.assertFalse(output.exists())

    def test_fold_seal_detects_any_artifact_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "fold-0"
            root.mkdir(parents=True)
            (root / "fold.json").write_text('{"fold":0}\n', encoding="utf-8")
            seal = create_proposal_seal(root)
            (root / "fold.json").write_text('{"fold":1}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                verify_proposal_seal(seal)

    def test_changed_held_out_bytes_fail_integrity_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self._calibration_sources(Path(temporary), date_count=1)[0]
            record = {
                "path": str(source.path),
                "observed_bytes": source.observed_bytes,
                "source_sha256": source.source_sha256,
            }
            source.path.write_bytes(source.path.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "size mismatch"):
                _verify_held_out_source(record)

    def test_missing_point_source_detail_rows_fail_integrity_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = [{"source_sha256": "a" * 64}, {"source_sha256": "b" * 64}]
            detail = {
                "source_sha256": "a" * 64,
                "unmasked_detection_count": 3,
                "accepted_visible_support_count": 2,
                "rejected_excluded_support_count": 1,
                "rejected_boundary_intersection_count": 0,
                "visible_sky_sources_rejected": 1,
            }
            (root / "point_source_audit.jsonl").write_text(json.dumps(detail) + "\n")
            (root / "point_source_audit_summary.json").write_text(
                json.dumps({"frame_count": 2}) + "\n"
            )
            with self.assertRaisesRegex(ValueError, "detail row count"):
                verify_completed_point_source_audit(records, root)

    def test_non_prefix_resumed_jsonl_fails_before_workers_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = [
                {"source_sha256": "a" * 64},
                {"source_sha256": "b" * 64},
            ]
            (root / "point_source_audit.jsonl").write_text(
                json.dumps({"source_sha256": "b" * 64}) + "\n"
            )
            with self.assertRaisesRegex(ValueError, "expected prefix"):
                _point_source_audit(records, np.ones((4, 4), dtype=bool), root, workers=1)


if __name__ == "__main__":
    unittest.main()
