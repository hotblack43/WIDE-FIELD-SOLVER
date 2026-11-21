"""End-to-end tests for the locked v26 automatic mask workflow."""
from __future__ import annotations

from dataclasses import asdict, replace
from contextlib import ExitStack
import fcntl
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image

from scripts.replay_visible_sky_cold_start import create_proposal_seal
from visible_sky_auto_workflow import (
    AutomaticWorkflowConfig,
    _verify_acceptance_inputs,
    run_automatic_workflow,
)
from visible_sky_calibration import (
    CalibrationSplit,
    CalibrationSource,
    DetectorSignature,
    approve_proposal,
    seal_artifact_inventory,
)
from visible_sky_registry import (
    activate_installation,
    active_installation,
    load_registry,
    register_calibration,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AutomaticWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.proposal_visible_fraction = None
        self.proposal_connected_components = 1
        self.held_out_detections = 200
        self.held_out_boundary = 5
        self.footprint_median = (9, 10)
        self.footprint_minimum = (4, 5)
        self.fold_override = None
        self.mixed_signature = False
        self.thin_proposal = False

    def _config_and_sources(self, root: Path) -> tuple[AutomaticWorkflowConfig, tuple[CalibrationSource, ...]]:
        archive = root / "archive"
        archive.mkdir()
        manifest = root / "downloads.sqlite"
        manifest.write_bytes(b"fixture manifest")
        sources = []
        for day in range(10):
            date = f"2026-10-{day + 1:02d}"
            for frame in range(10):
                path = archive / f"{date.replace('-', '_')}_{frame:02d}.fits"
                path.write_bytes(f"native-{day}-{frame}".encode())
                sources.append(
                    CalibrationSource(
                        path=path,
                        source_sha256=_sha256(path),
                        observed_bytes=path.stat().st_size,
                        source_id="source-a",
                        camera_id="camera-a",
                        observed_utc=f"{date}T{frame:02d}:00:00Z",
                        observation_date=date,
                        remote_url=f"https://example.invalid/{path.name}",
                    )
                )
        config = AutomaticWorkflowConfig(
            source_id="source-a",
            camera_id="camera-a",
            installation_id="installation-a",
            orientation="native",
            download_manifest=manifest,
            archive_root=archive,
            review_root=root / "review",
            calibration_root=root / "calibrations",
        )
        return config, tuple(sources)

    def _fake_proposal(
        self,
        sources,
        *,
        output,
        source_id,
        camera_id,
        installation_id,
        orientation,
        date_split_payload=None,
        detector_signature_override=None,
    ):
        output = Path(output)
        output.mkdir(parents=True)
        yy, xx = np.indices((48, 64))
        mask = (
            (xx >= 28) & (xx <= 34)
            if self.thin_proposal
            else np.hypot(xx - 31.5, yy - 23.5) < 20
        )
        draft = output / f"{installation_id}.draft.png"
        Image.fromarray(np.where(mask, 255, 0).astype(np.uint8), mode="L").save(draft)
        rgb = np.repeat(np.uint8(mask * 180)[..., None], 3, axis=2)
        for name in ("temporal_reference.png", "boundary_review.png", "boundary_review_inverted.png"):
            Image.fromarray(rgb, mode="RGB").save(output / name)
        artifacts = {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file()
        }
        signature = detector_signature_override or DetectorSignature(
            (48, 64), "two_dimensional", ("L",), "CAMERA-A", orientation
        )
        visible_pixels = int(mask.sum())
        if self.proposal_visible_fraction is not None:
            visible_pixels = round(self.proposal_visible_fraction * mask.size)
        selection = {
            "status": "draft_not_approved",
            "production_eligible": False,
            "draft_id": f"{installation_id}-fixture",
            "source_id": source_id,
            "camera_id": camera_id,
            "installation_id": installation_id,
            "orientation": orientation,
            "coordinate_convention": "array[y, x]; origin top-left",
            "spatial_shape": [48, 64],
            "detector_signature": asdict(signature),
            "selection": {
                "method": "fixture",
                "source_count": len(sources),
                "sources": [
                    {"source_sha256": source.source_sha256, "observation_date": source.observation_date}
                    for source in sources
                ],
            },
            "proposal": {
                "method": "fixture",
                "connected_components": self.proposal_connected_components,
                "visible_fraction": visible_pixels / mask.size,
                "visible_pixels": visible_pixels,
            },
            "generation_code_sha256": "1" * 64,
            "artifacts": artifacts,
        }
        selection["seal"] = seal_artifact_inventory(artifacts, selection)
        (output / "selection.json").write_text(
            json.dumps(selection, indent=2, sort_keys=True) + "\n"
        )
        split = date_split_payload or {
            "schema": "fixture",
            "calibration_dates": sorted({source.observation_date for source in sources}),
            "holdout_dates": [],
            "holdout_sources": [],
        }
        (output / "date-split.json").write_text(
            json.dumps(split, indent=2, sort_keys=True) + "\n"
        )
        return create_proposal_seal(output)

    def _fake_held_out(self, root: Path, proposal: np.ndarray) -> dict[str, object]:
        split = json.loads((root / "date-split.json").read_text())
        records = split["holdout_sources"]
        destination = root / "held-out"
        destination.mkdir()
        rows = []
        remaining_detections = self.held_out_detections
        remaining_boundary = self.held_out_boundary
        for index, record in enumerate(records):
            frame_count = remaining_detections // (len(records) - index)
            boundary = min(remaining_boundary, frame_count)
            remaining_detections -= frame_count
            remaining_boundary -= boundary
            rows.append({
                "source_sha256": record["source_sha256"],
                "unmasked_detection_count": frame_count,
                "accepted_visible_support_count": frame_count - boundary,
                "rejected_excluded_support_count": 0,
                "rejected_boundary_intersection_count": boundary,
                "visible_sky_sources_rejected": boundary,
            })
        (destination / "point_source_audit.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        )
        point = {
            "status": "sealed_proposal_held_out_point_sources_audited",
            "frame_count": len(rows),
            "unmasked_detection_count": self.held_out_detections,
            "accepted_visible_support_count": self.held_out_detections - self.held_out_boundary,
            "rejected_excluded_support_count": 0,
            "rejected_boundary_intersection_count": self.held_out_boundary,
            "visible_sky_sources_rejected": self.held_out_boundary,
            "detail_file": "point_source_audit.jsonl",
        }
        (destination / "point_source_audit_summary.json").write_text(
            json.dumps(point, indent=2, sort_keys=True) + "\n"
        )
        summary = {
            "status": "held_out_processed_before_reference_reveal",
            "source_count": len(rows),
            "date_count": 2,
            "footprint_iou_median_ratio": {
                "numerator": self.footprint_median[0],
                "denominator": self.footprint_median[1],
            },
            "footprint_iou_minimum_ratio": {
                "numerator": self.footprint_minimum[0],
                "denominator": self.footprint_minimum[1],
            },
            "point_sources": point,
        }
        (destination / "detection_audit_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n"
        )
        return summary

    def _run_patched(
        self,
        config: AutomaticWorkflowConfig,
        sources: tuple[CalibrationSource, ...],
        *,
        now_utc: str,
        replace_active: bool = False,
        split: CalibrationSplit | None = None,
        activation_side_effect=None,
        atomic_side_effect=None,
    ):
        signature = DetectorSignature(
            (48, 64), "two_dimensional", ("L",), "CAMERA-A", "native"
        )

        def signature_for(path, *, orientation):
            if self.mixed_signature and Path(path) == sources[-1].path:
                return DetectorSignature(
                    (49, 64), "two_dimensional", ("L",), "CAMERA-A", orientation
                )
            return signature

        with ExitStack() as stack:
            stack.enter_context(mock.patch(
                "visible_sky_auto_workflow.verified_sources_from_manifest",
                return_value=sources,
            ))
            stack.enter_context(mock.patch(
                "visible_sky_auto_workflow.archive_detector_signature",
                side_effect=signature_for,
            ))
            stack.enter_context(mock.patch(
                "visible_sky_auto_workflow.create_sealed_proposal_from_sources",
                side_effect=self._fake_proposal,
            ))
            stack.enter_context(mock.patch(
                "visible_sky_auto_workflow._held_out_evaluation",
                side_effect=self._fake_held_out,
            ))
            if split is not None:
                stack.enter_context(mock.patch(
                    "visible_sky_auto_workflow.partition_dates", return_value=split
                ))
            if self.fold_override is not None:
                stack.enter_context(mock.patch(
                    "visible_sky_auto_workflow.comparison_metrics",
                    return_value=self.fold_override,
                ))
            if activation_side_effect is not None:
                stack.enter_context(mock.patch(
                    "visible_sky_auto_workflow.activate_installation",
                    side_effect=activation_side_effect,
                ))
            if atomic_side_effect is not None:
                stack.enter_context(mock.patch(
                    "visible_sky_auto_workflow.atomic_write_json",
                    side_effect=atomic_side_effect,
                ))
            return run_automatic_workflow(
                config, replace_active=replace_active, now_utc=now_utc
            )

    def test_success_runs_primary_holdout_folds_acceptance_registration_and_activation_in_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, sources = self._config_and_sources(root)
            original_bytes = {source.path: source.path.read_bytes() for source in sources}
            result = self._run_patched(
                config, sources, now_utc="2026-11-16T12:34:56Z"
            )

            self.assertEqual(result.status, "activated")
            self.assertEqual(result.exit_code, 0)
            self.assertIsNotNone(result.manifest_path)
            receipt = json.loads(result.receipt_path.read_text())
            self.assertEqual(receipt["status"], "activated")
            self.assertEqual(
                receipt["stages"],
                ["sources", "primary", "held_out", "folds", "gates", "acceptance", "approval", "registration", "activation"],
            )
            acceptance_path = Path(receipt["automatic_acceptance_path"])
            self.assertTrue(acceptance_path.is_file())
            acceptance_hash = hashlib.sha256(acceptance_path.read_bytes()).hexdigest()
            self.assertEqual(acceptance_path.stem, acceptance_hash)
            manifest = json.loads(result.manifest_path.read_text())
            expected_mask_id = (
                f"installation-a-auto-{manifest['mask_sha256'][:12]}-{acceptance_hash[:12]}"
            )
            self.assertEqual(manifest["mask_id"], expected_mask_id)
            self.assertEqual(manifest["approval"]["approval_mode"], "automated_validation")
            active = active_installation(
                (config.calibration_root / "registry.jsonl",),
                source_id="source-a",
                camera_id="camera-a",
            )
            self.assertEqual(active["installation_id"], "installation-a")
            self.assertEqual(
                [row["record_type"] for row in load_registry((config.calibration_root / "registry.jsonl",))],
                ["calibration", "activation"],
            )
            self.assertEqual(
                {source.path: source.path.read_bytes() for source in sources}, original_bytes
            )

    def _split_with_dates(
        self,
        sources: tuple[CalibrationSource, ...],
        calibration_dates: tuple[str, ...],
        holdout_dates: tuple[str, ...],
        *,
        duplicate_holdout: bool = False,
    ) -> CalibrationSplit:
        calibration = tuple(
            source for source in sources if source.observation_date in calibration_dates
        )
        holdout = tuple(source for source in sources if source.observation_date in holdout_dates)
        if duplicate_holdout:
            holdout = holdout + holdout
        selected = tuple(
            next(source for source in calibration if source.observation_date == date)
            for date in calibration_dates
        )
        return CalibrationSplit(
            calibration_dates,
            holdout_dates,
            calibration,
            holdout,
            selected,
        )

    def test_each_failed_gate_writes_rejection_and_preserves_registry_bytes(self):
        cases = (
            ("insufficient-total", "total_date_count_minimum"),
            ("insufficient-calibration", "calibration_date_count_minimum"),
            ("insufficient-holdout-dates", "held_out_date_count_minimum"),
            ("insufficient-held-out-frames", "held_out_source_count_minimum"),
            ("mixed-signature", "detector_signature_count_exact"),
            ("visible-low", "proposal_visible_fraction_minimum"),
            ("visible-high", "proposal_visible_fraction_maximum"),
            ("footprint-median", "held_out_footprint_iou_median_minimum"),
            ("footprint-minimum", "held_out_footprint_iou_minimum_minimum"),
            ("detections", "held_out_unmasked_detection_count_minimum"),
            ("boundary", "held_out_boundary_intersection_fraction_maximum"),
            ("fold-iou", "fold_0_mask_iou_minimum"),
            ("fold-mean", "fold_0_boundary_distance_mean_pixels_maximum"),
            ("fold-p95", "fold_0_boundary_distance_p95_pixels_maximum"),
        )
        for ordinal, (case, expected_gate) in enumerate(cases):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                self.setUp()
                root = Path(temporary)
                config, all_sources = self._config_and_sources(root)
                sources = all_sources
                split = None
                dates = tuple(sorted({source.observation_date for source in all_sources}))
                if case == "insufficient-total":
                    sources = tuple(source for source in all_sources if source.observation_date != dates[-1])
                elif case == "insufficient-calibration":
                    split = self._split_with_dates(all_sources, dates[:7], dates[7:])
                elif case == "insufficient-holdout-dates":
                    split = self._split_with_dates(
                        all_sources, dates[:9], dates[9:], duplicate_holdout=True
                    )
                elif case == "insufficient-held-out-frames":
                    sources = tuple(source for source in all_sources if int(source.observed_utc[11:13]) == 0)
                elif case == "mixed-signature":
                    self.mixed_signature = True
                elif case == "visible-low":
                    self.proposal_visible_fraction = 0.09
                elif case == "visible-high":
                    self.proposal_visible_fraction = 0.96
                elif case == "footprint-median":
                    self.footprint_median = (79, 100)
                elif case == "footprint-minimum":
                    self.footprint_minimum = (49, 100)
                elif case == "detections":
                    self.held_out_detections = 99
                    self.held_out_boundary = 4
                elif case == "boundary":
                    self.held_out_boundary = 11
                elif case.startswith("fold-"):
                    self.fold_override = {
                        "intersection_pixels": 94 if case == "fold-iou" else 100,
                        "union_pixels": 100,
                        "boundary_distance_mean_pixels": 10.01 if case == "fold-mean" else 0.0,
                        "boundary_distance_p95_pixels": 24.01 if case == "fold-p95" else 0.0,
                    }
                registry = config.calibration_root / "registry.jsonl"
                before = registry.read_bytes() if registry.exists() else b""
                result = self._run_patched(
                    config,
                    sources,
                    now_utc=f"2026-11-16T13:{ordinal:02d}:00Z",
                    split=split,
                )
                self.assertEqual(result.status, "rejected")
                self.assertEqual(result.exit_code, 1)
                receipt = json.loads(result.receipt_path.read_text())
                self.assertIn(expected_gate, receipt["failed_gates"])
                after = registry.read_bytes() if registry.exists() else b""
                self.assertEqual(after, before)

    def test_zero_or_one_date_are_durable_scientific_rejections(self):
        for date_count in (0, 1):
            with self.subTest(date_count=date_count), tempfile.TemporaryDirectory() as temporary:
                config, all_sources = self._config_and_sources(Path(temporary))
                dates = sorted({source.observation_date for source in all_sources})
                selected = tuple(
                    source
                    for source in all_sources
                    if source.observation_date in set(dates[:date_count])
                )

                result = self._run_patched(
                    config,
                    selected,
                    now_utc=f"2026-11-16T13:5{date_count}:00Z",
                )

                self.assertEqual(result.status, "rejected")
                self.assertEqual(result.exit_code, 1)
                receipt = json.loads(result.receipt_path.read_text())
                self.assertEqual(receipt["status"], "rejected")
                self.assertIn("total_date_count_minimum", receipt["failed_gates"])
                self.assertFalse((config.calibration_root / "registry.jsonl").exists())

    def _seed_active_installation(
        self, config: AutomaticWorkflowConfig, source: CalibrationSource, installation: str
    ) -> None:
        proposal_root = config.review_root / f"seed-{installation}"
        self._fake_proposal(
            (source,),
            output=proposal_root,
            source_id=config.source_id,
            camera_id=config.camera_id,
            installation_id=installation,
            orientation=config.orientation,
        )
        selection = json.loads((proposal_root / "selection.json").read_text())
        draft = f"{installation}.draft.png"
        manifest = approve_proposal(
            proposal_root / "selection.json",
            config.calibration_root,
            reviewed_draft_sha256=selection["artifacts"][draft],
            mask_id=f"{installation}-mask",
            approved_by="fixture",
            safety_margin_pixels=5,
        )
        registry = config.calibration_root / "registry.jsonl"
        register_calibration(
            registry, manifest, source_id=config.source_id, camera_id=config.camera_id
        )
        activate_installation(
            registry,
            source_id=config.source_id,
            camera_id=config.camera_id,
            installation_id=installation,
        )

    def test_no_active_installation_activates(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, sources = self._config_and_sources(Path(temporary))
            result = self._run_patched(config, sources, now_utc="2026-11-16T14:00:00Z")
            self.assertEqual(result.status, "activated")

    def test_same_active_installation_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, sources = self._config_and_sources(Path(temporary))
            first = self._run_patched(config, sources, now_utc="2026-11-16T14:01:00Z")
            registry = config.calibration_root / "registry.jsonl"
            before = registry.read_bytes()
            second = self._run_patched(config, sources, now_utc="2026-11-16T14:02:00Z")
            self.assertEqual(first.status, "activated")
            self.assertEqual(second.status, "activated")
            self.assertEqual(registry.read_bytes(), before)
            self.assertEqual(first.manifest_path, second.manifest_path)

    def test_different_active_installation_refuses_before_run_without_replace(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, sources = self._config_and_sources(Path(temporary))
            self._seed_active_installation(config, sources[0], "installation-old")
            registry = config.calibration_root / "registry.jsonl"
            before = registry.read_bytes()
            result = self._run_patched(config, sources, now_utc="2026-11-16T14:03:00Z")
            self.assertEqual(result.exit_code, 2)
            self.assertFalse(result.run_root.exists())
            self.assertEqual(registry.read_bytes(), before)

    def test_replace_active_switches_only_after_all_gates_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, sources = self._config_and_sources(Path(temporary))
            self._seed_active_installation(config, sources[0], "installation-old")
            result = self._run_patched(
                config,
                sources,
                now_utc="2026-11-16T14:04:00Z",
                replace_active=True,
            )
            self.assertEqual(result.status, "activated")
            active = active_installation(
                (config.calibration_root / "registry.jsonl",),
                source_id=config.source_id,
                camera_id=config.camera_id,
            )
            self.assertEqual(active["installation_id"], config.installation_id)

    def test_identical_rerun_reuses_content_addressed_acceptance_without_registry_conflict(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, sources = self._config_and_sources(Path(temporary))
            first = self._run_patched(config, sources, now_utc="2026-11-16T14:05:00Z")
            second = self._run_patched(config, sources, now_utc="2026-11-16T14:06:00Z")
            first_receipt = json.loads(first.receipt_path.read_text())
            second_receipt = json.loads(second.receipt_path.read_text())
            self.assertEqual(
                first_receipt["automatic_acceptance_sha256"],
                second_receipt["automatic_acceptance_sha256"],
            )
            self.assertEqual(len(load_registry((config.calibration_root / "registry.jsonl",))), 2)

    def test_new_evidence_same_installation_publishes_and_activates_new_mask(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, sources = self._config_and_sources(Path(temporary))
            first = self._run_patched(
                config, sources, now_utc="2026-11-16T14:05:00Z"
            )
            changed_path = sources[0].path
            changed_path.write_bytes(changed_path.read_bytes() + b"-new-evidence")
            changed = replace(
                sources[0],
                source_sha256=_sha256(changed_path),
                observed_bytes=changed_path.stat().st_size,
            )
            second_sources = (changed, *sources[1:])
            second = self._run_patched(
                config, second_sources, now_utc="2026-11-16T14:06:00Z"
            )
            self.assertEqual((first.status, second.status), ("activated", "activated"))
            first_manifest = json.loads(first.manifest_path.read_text())
            second_manifest = json.loads(second.manifest_path.read_text())
            self.assertNotEqual(first_manifest["mask_id"], second_manifest["mask_id"])
            active = active_installation(
                (config.calibration_root / "registry.jsonl",),
                source_id=config.source_id,
                camera_id=config.camera_id,
            )
            self.assertEqual(active["mask_id"], second_manifest["mask_id"])

    def test_safety_margin_cannot_activate_an_all_excluded_mask(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.thin_proposal = True
            config, sources = self._config_and_sources(Path(temporary))
            result = self._run_patched(
                config, sources, now_utc="2026-11-16T14:06:30Z"
            )
            self.assertEqual(result.status, "rejected")
            receipt = json.loads(result.receipt_path.read_text())
            self.assertIn(
                "finalized_visible_fraction_minimum", receipt["failed_gates"]
            )
            self.assertFalse((config.calibration_root / "registry.jsonl").exists())

    def test_second_process_lock_refuses_before_run_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, sources = self._config_and_sources(Path(temporary))
            config.calibration_root.mkdir()
            lock_path = config.calibration_root / ".auto-source-a-camera-a.lock"
            with lock_path.open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = self._run_patched(
                    config, sources, now_utc="2026-11-16T14:07:00Z"
                )
            self.assertEqual(result.exit_code, 3)
            self.assertFalse(result.run_root.exists())

    def test_registration_then_activation_failure_records_registered_inactive_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, sources = self._config_and_sources(Path(temporary))
            result = self._run_patched(
                config,
                sources,
                now_utc="2026-11-16T14:08:00Z",
                activation_side_effect=RuntimeError("activation stopped"),
            )
            self.assertEqual(result.status, "operational_failure")
            receipt = json.loads(result.receipt_path.read_text())
            self.assertEqual(receipt["partial_state"], "registered_inactive")
            records = load_registry((config.calibration_root / "registry.jsonl",))
            self.assertEqual([row["record_type"] for row in records], ["calibration"])

    def test_post_activation_receipt_failure_reports_active_without_rollback(self):
        from visible_sky_automatic import atomic_write_json as real_atomic_write_json

        with tempfile.TemporaryDirectory() as temporary:
            config, sources = self._config_and_sources(Path(temporary))

            def fail_final_receipt(path, payload):
                if Path(path).name == "automatic_run.json" and payload.get("status") == "activated":
                    raise OSError("final receipt stopped")
                return real_atomic_write_json(path, payload)

            result = self._run_patched(
                config,
                sources,
                now_utc="2026-11-16T14:09:00Z",
                atomic_side_effect=fail_final_receipt,
            )
            self.assertEqual(result.status, "activated")
            self.assertEqual(result.exit_code, 0)
            active = active_installation(
                (config.calibration_root / "registry.jsonl",),
                source_id=config.source_id,
                camera_id=config.camera_id,
            )
            self.assertEqual(active["installation_id"], config.installation_id)

    def test_tampered_proposal_fold_audit_mask_or_acceptance_fails_before_registry(self):
        mutations = ("proposal", "fold", "held-out", "finalized-mask", "acceptance")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config, sources = self._config_and_sources(root)
                primary = root / "primary"
                fold = root / "fold-0"
                primary_seal = self._fake_proposal(
                    sources[:8],
                    output=primary,
                    source_id=config.source_id,
                    camera_id=config.camera_id,
                    installation_id=config.installation_id,
                    orientation=config.orientation,
                    date_split_payload={
                        "holdout_sources": [
                            {
                                **asdict(source),
                                "path": str(source.path),
                            }
                            for source in sources[80:]
                        ]
                    },
                )
                fold_seal = self._fake_proposal(
                    sources[:7],
                    output=fold,
                    source_id=config.source_id,
                    camera_id=config.camera_id,
                    installation_id=config.installation_id,
                    orientation=config.orientation,
                )
                proposal = np.asarray(
                    Image.open(primary / "installation-a.draft.png").convert("L")
                ) == 255
                self._fake_held_out(primary, proposal)
                held_out = primary / "held-out"
                held_out_records = [
                    {**asdict(source), "path": str(source.path)} for source in sources[80:]
                ]
                finalized = root / "finalized-mask.png"
                finalized.write_bytes(b"final mask evidence")
                finalized_hash = _sha256(finalized)
                acceptance = root / "acceptance.json"
                acceptance.write_bytes(b'{"status":"pass"}')
                acceptance_hash = _sha256(acceptance)
                if mutation == "proposal":
                    (primary / "installation-a.draft.png").write_bytes(b"tampered")
                elif mutation == "fold":
                    (fold / "selection.json").write_bytes(b"tampered")
                elif mutation == "held-out":
                    detail = held_out / "point_source_audit.jsonl"
                    detail.write_text("\n".join(detail.read_text().splitlines()[:-1]) + "\n")
                elif mutation == "finalized-mask":
                    finalized.write_bytes(finalized.read_bytes() + b"tampered")
                else:
                    acceptance.write_bytes(acceptance.read_bytes() + b"tampered")
                with self.assertRaises((ValueError, FileNotFoundError)):
                    _verify_acceptance_inputs(
                        [primary_seal, fold_seal],
                        held_out_records,
                        held_out,
                        finalized,
                        finalized_hash,
                        acceptance,
                        acceptance_hash,
                        {},
                        {},
                        {},
                        [],
                    )
                self.assertFalse((config.calibration_root / "registry.jsonl").exists())

    def test_post_acceptance_comparison_or_detection_tamper_fails_before_registry(self):
        from visible_sky_automatic import atomic_write_json as real_atomic_write_json

        for target in ("comparison", "detection-summary"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config, sources = self._config_and_sources(root)

                def publish_then_tamper(path, payload):
                    real_atomic_write_json(path, payload)
                    if payload.get("schema") != "visible-sky-automatic-v1":
                        return
                    run_root = (
                        config.review_root
                        / config.installation_id
                        / "auto-20261116T141000Z"
                    )
                    if target == "comparison":
                        evidence = run_root / "fold-0/comparison.json"
                    else:
                        evidence = (
                            run_root
                            / "primary/held-out/detection_audit_summary.json"
                        )
                    evidence.write_bytes(evidence.read_bytes() + b"\n")

                result = self._run_patched(
                    config,
                    sources,
                    now_utc="2026-11-16T14:10:00Z",
                    atomic_side_effect=publish_then_tamper,
                )
                self.assertEqual(result.status, "operational_failure")
                self.assertFalse((config.calibration_root / "registry.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
