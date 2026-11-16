"""Locked one-command automatic visible-sky calibration workflow."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Literal, Mapping

import numpy as np
from PIL import Image
from scipy.ndimage import label

from scripts.replay_visible_sky_cold_start import (
    _held_out_evaluation,
    archive_detector_signature,
    calibration_date_folds,
    comparison_metrics,
    create_sealed_proposal_from_sources,
    verify_completed_point_source_audit,
    verify_proposal_seal,
)
from visible_sky_automatic import (
    atomic_write_json,
    automatic_mask_id,
    canonical_acceptance_payload,
    canonical_json_sha256,
    evaluate_automatic_gates,
    validate_automatic_acceptance,
)
from visible_sky_calibration import (
    CalibrationSplit,
    SAFE_IDENTIFIER,
    approve_proposal,
    finalize_binary_mask,
    partition_dates,
    require_single_detector_signature,
    verified_sources_from_manifest,
)
from visible_sky_registry import (
    activate_installation,
    active_installation,
    register_calibration,
)


@dataclass(frozen=True)
class AutomaticWorkflowConfig:
    source_id: str
    camera_id: str
    installation_id: str
    orientation: str
    download_manifest: Path
    archive_root: Path
    review_root: Path
    calibration_root: Path

    def __post_init__(self) -> None:
        for name in ("source_id", "camera_id", "installation_id", "orientation"):
            value = getattr(self, name)
            if not isinstance(value, str) or SAFE_IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"{name} must match [A-Za-z0-9][A-Za-z0-9._-]*")
        for name in ("download_manifest", "archive_root", "review_root", "calibration_root"):
            object.__setattr__(self, name, Path(getattr(self, name)).expanduser().resolve())
        if not self.download_manifest.is_file():
            raise ValueError(f"download_manifest is not a file: {self.download_manifest}")
        if not self.archive_root.is_dir():
            raise ValueError(f"archive_root is not a directory: {self.archive_root}")


@dataclass(frozen=True)
class AutomaticWorkflowResult:
    status: Literal["activated", "rejected", "operational_failure"]
    exit_code: int
    run_root: Path
    receipt_path: Path
    manifest_path: Path | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run_stamp(now_utc: str | None) -> tuple[str, str]:
    if now_utc is None:
        moment = datetime.now(timezone.utc)
    else:
        try:
            moment = datetime.fromisoformat(now_utc.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid now_utc: {now_utc!r}") from exc
        if moment.tzinfo is None:
            raise ValueError("now_utc must include a timezone")
        moment = moment.astimezone(timezone.utc)
    text = moment.isoformat(timespec="seconds").replace("+00:00", "Z")
    return text, moment.strftime("%Y%m%dT%H%M%SZ")


def _source_payload(source) -> dict[str, object]:
    payload = asdict(source)
    payload["path"] = str(source.path)
    return payload


def _split_payload(sources, split) -> dict[str, object]:
    return {
        "schema": "wide-field-solver-visible-sky-cold-start-split-v1",
        "holdout_modulus": 5,
        "holdout_remainder": 0,
        "source_count": len(sources),
        "calibration_dates": list(split.calibration_dates),
        "holdout_dates": list(split.holdout_dates),
        "calibration_sources": [_source_payload(source) for source in split.calibration_sources],
        "holdout_sources": [_source_payload(source) for source in split.holdout_sources],
        "selected_calibration_sources": [
            _source_payload(source) for source in split.selected_calibration_sources
        ],
    }


def _draft(root: Path) -> tuple[Path, dict[str, object]]:
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    names = [name for name in selection["artifacts"] if name.endswith(".draft.png")]
    if len(names) != 1:
        raise ValueError(f"proposal does not contain exactly one draft mask: {root}")
    return root / names[0], selection


def _passing_fold_metrics() -> list[dict[str, object]]:
    return [
        {
            "fold_index": index,
            "mask_intersection_count": 95,
            "mask_union_count": 100,
            "boundary_distance_mean_pixels": 0.0,
            "boundary_distance_p95_pixels": 0.0,
        }
        for index in range(5)
    ]


def _preflight_metrics(sources, split, signature_count: int) -> dict[str, object]:
    return {
        "total_date_count": len({source.observation_date for source in sources}),
        "calibration_date_count": len(split.calibration_dates),
        "held_out_date_count": len(split.holdout_dates),
        "held_out_source_count": len(split.holdout_sources),
        "detector_signature_count": signature_count,
        "proposal_visible_pixel_count": 50,
        "proposal_pixel_count": 100,
        "proposal_connected_component_count": 1,
        "finalized_visible_pixel_count": 50,
        "finalized_pixel_count": 100,
        "finalized_connected_component_count": 1,
        "held_out_footprint_iou_median_numerator": 9,
        "held_out_footprint_iou_median_denominator": 10,
        "held_out_footprint_iou_minimum_numerator": 4,
        "held_out_footprint_iou_minimum_denominator": 5,
        "held_out_unmasked_detection_count": 100,
        "held_out_boundary_intersection_count": 0,
    }


def _gate_metrics(sources, split, signature_count, selection, held_out) -> dict[str, object]:
    proposal = selection["proposal"]
    shape = selection["spatial_shape"]
    median = held_out["footprint_iou_median_ratio"]
    minimum = held_out["footprint_iou_minimum_ratio"]
    point = held_out["point_sources"]
    return {
        "total_date_count": len({source.observation_date for source in sources}),
        "calibration_date_count": len(split.calibration_dates),
        "held_out_date_count": len(split.holdout_dates),
        "held_out_source_count": len(split.holdout_sources),
        "detector_signature_count": signature_count,
        "proposal_visible_pixel_count": int(proposal["visible_pixels"]),
        "proposal_pixel_count": int(np.prod(shape)),
        "proposal_connected_component_count": int(proposal["connected_components"]),
        "finalized_visible_pixel_count": int(proposal["visible_pixels"]),
        "finalized_pixel_count": int(np.prod(shape)),
        "finalized_connected_component_count": int(proposal["connected_components"]),
        "held_out_footprint_iou_median_numerator": int(median["numerator"]),
        "held_out_footprint_iou_median_denominator": int(median["denominator"]),
        "held_out_footprint_iou_minimum_numerator": int(minimum["numerator"]),
        "held_out_footprint_iou_minimum_denominator": int(minimum["denominator"]),
        "held_out_unmasked_detection_count": int(point["unmasked_detection_count"]),
        "held_out_boundary_intersection_count": int(
            point["rejected_boundary_intersection_count"]
        ),
    }


def _reject(
    receipt_path: Path,
    receipt: dict[str, object],
    evaluation: Mapping[str, object],
    run_root: Path,
) -> AutomaticWorkflowResult:
    receipt.update(
        status="rejected",
        exit_code=1,
        gate_evaluation=dict(evaluation),
        failed_gates=list(evaluation["failed_gates"]),
    )
    atomic_write_json(receipt_path, receipt)
    return AutomaticWorkflowResult("rejected", 1, run_root, receipt_path, None)


def _verify_acceptance_inputs(
    seals: list[Path],
    held_out_records,
    held_out_root: Path,
    finalized_mask: Path,
    finalized_sha256: str,
    acceptance_path: Path,
    acceptance_sha256: str,
    evidence_paths: Mapping[str, Path],
    code_paths: Mapping[str, Path],
    expected_metrics: Mapping[str, object],
    expected_fold_metrics: list[dict[str, object]],
) -> None:
    for seal in seals:
        verify_proposal_seal(seal)
    verify_completed_point_source_audit(held_out_records, held_out_root)
    if _sha256(finalized_mask) != finalized_sha256:
        raise ValueError("finalized automatic mask checksum mismatch")
    if _sha256(acceptance_path) != acceptance_sha256:
        raise ValueError("canonical automatic acceptance checksum mismatch")
    try:
        payload = json.loads(acceptance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("canonical automatic acceptance is unreadable") from exc
    validated = validate_automatic_acceptance(
        payload, expected_finalized_mask_sha256=finalized_sha256
    )
    current_artifacts = {
        name: _sha256(path) for name, path in evidence_paths.items()
    }
    current_code = {name: _sha256(path) for name, path in code_paths.items()}
    if validated["artifact_sha256"] != dict(sorted(current_artifacts.items())):
        raise ValueError("automatic acceptance artifact inventory mismatch")
    if validated["code_sha256"] != dict(sorted(current_code.items())):
        raise ValueError("automatic acceptance code inventory mismatch")
    if validated["metrics"] != dict(expected_metrics):
        raise ValueError("automatic acceptance metric mismatch")
    if validated["fold_metrics"] != sorted(
        expected_fold_metrics, key=lambda row: row["fold_index"]
    ):
        raise ValueError("automatic acceptance fold metric mismatch")


def run_automatic_workflow(
    config: AutomaticWorkflowConfig,
    *,
    replace_active: bool = False,
    now_utc: str | None = None,
) -> AutomaticWorkflowResult:
    """Validate, accept, register, and activate one installation automatically."""
    timestamp, stamp = _run_stamp(now_utc)
    predicted_root = config.review_root / config.installation_id / f"auto-{stamp}"
    predicted_receipt = predicted_root / "automatic_run.json"
    config.calibration_root.mkdir(parents=True, exist_ok=True)
    lock_path = config.calibration_root / f".auto-{config.source_id}-{config.camera_id}.lock"
    registry_path = config.calibration_root / "registry.jsonl"
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return AutomaticWorkflowResult(
                "operational_failure", 3, predicted_root, predicted_receipt, None
            )

        prior_active = None
        if registry_path.is_file():
            prior_active = active_installation(
                (registry_path,), source_id=config.source_id, camera_id=config.camera_id
            )
        if (
            prior_active is not None
            and prior_active["installation_id"] != config.installation_id
            and not replace_active
        ):
            return AutomaticWorkflowResult(
                "operational_failure", 2, predicted_root, predicted_receipt, None
            )

        if predicted_root.exists():
            return AutomaticWorkflowResult(
                "operational_failure", 3, predicted_root, predicted_receipt, None
            )
        predicted_root.mkdir(parents=True)
        receipt: dict[str, object] = {
            "schema": "wide-field-solver-visible-sky-automatic-run-v1",
            "status": "running",
            "exit_code": None,
            "started_utc": timestamp,
            "source_id": config.source_id,
            "camera_id": config.camera_id,
            "installation_id": config.installation_id,
            "orientation": config.orientation,
            "run_root": str(predicted_root),
            "stages": [],
        }
        atomic_write_json(predicted_receipt, receipt)
        manifest_path: Path | None = None
        activated = False
        registered = False
        try:
            sources = verified_sources_from_manifest(
                config.download_manifest,
                config.archive_root,
                config.source_id,
                config.camera_id,
            )
            dates = tuple(sorted({source.observation_date for source in sources}))
            if len(dates) < 2:
                split = CalibrationSplit(
                    calibration_dates=(),
                    holdout_dates=dates,
                    calibration_sources=(),
                    holdout_sources=tuple(sources),
                    selected_calibration_sources=(),
                )
            else:
                split = partition_dates(
                    sources, holdout_modulus=5, holdout_remainder=0
                )
            signature_rows = tuple(
                (
                    source.path,
                    archive_detector_signature(source.path, orientation=config.orientation),
                )
                for source in sources
            )
            signature_keys = {
                json.dumps(asdict(signature), sort_keys=True, separators=(",", ":"))
                for _path, signature in signature_rows
            }
            receipt["stages"].append("sources")
            preflight = evaluate_automatic_gates(
                _preflight_metrics(sources, split, len(signature_keys)),
                _passing_fold_metrics(),
            )
            preflight_names = {
                "total_date_count_minimum",
                "calibration_date_count_minimum",
                "held_out_date_count_minimum",
                "held_out_source_count_minimum",
                "detector_signature_count_exact",
            }
            if any(name in preflight_names for name in preflight["failed_gates"]):
                return _reject(predicted_receipt, receipt, preflight, predicted_root)
            signature = require_single_detector_signature(signature_rows)

            primary_root = predicted_root / "primary"
            primary_seal = create_sealed_proposal_from_sources(
                split.selected_calibration_sources,
                output=primary_root,
                source_id=config.source_id,
                camera_id=config.camera_id,
                installation_id=config.installation_id,
                orientation=config.orientation,
                date_split_payload=_split_payload(sources, split),
                detector_signature_override=signature,
            )
            verify_proposal_seal(primary_seal)
            draft_path, selection = _draft(primary_root)
            proposal = np.asarray(Image.open(draft_path).convert("L")) == 255
            receipt["stages"].append("primary")

            held_out = _held_out_evaluation(primary_root, proposal)
            held_out_root = primary_root / "held-out"
            verify_completed_point_source_audit(
                [_source_payload(source) for source in split.holdout_sources], held_out_root
            )
            receipt["stages"].append("held_out")

            fold_metrics: list[dict[str, object]] = []
            fold_seals: list[Path] = []
            for index, fold_sources in enumerate(
                calibration_date_folds(split.calibration_sources)
            ):
                fold_root = predicted_root / f"fold-{index}"
                seal = create_sealed_proposal_from_sources(
                    fold_sources,
                    output=fold_root,
                    source_id=config.source_id,
                    camera_id=config.camera_id,
                    installation_id=config.installation_id,
                    orientation=config.orientation,
                    detector_signature_override=signature,
                )
                verify_proposal_seal(seal)
                fold_draft, _fold_selection = _draft(fold_root)
                fold_mask = np.asarray(Image.open(fold_draft).convert("L")) == 255
                comparison = comparison_metrics(fold_mask, proposal)
                row = {
                    "fold_index": index,
                    "mask_intersection_count": int(comparison["intersection_pixels"]),
                    "mask_union_count": int(comparison["union_pixels"]),
                    "boundary_distance_mean_pixels": float(
                        comparison["boundary_distance_mean_pixels"]
                    ),
                    "boundary_distance_p95_pixels": float(
                        comparison["boundary_distance_p95_pixels"]
                    ),
                }
                fold_metrics.append(row)
                atomic_write_json(fold_root / "comparison.json", row)
                fold_seals.append(seal)
            receipt["stages"].append("folds")

            metrics = _gate_metrics(
                sources, split, len(signature_keys), selection, held_out
            )
            evaluation = evaluate_automatic_gates(metrics, fold_metrics)
            receipt["stages"].append("gates")
            receipt["gate_evaluation"] = evaluation
            if evaluation["status"] != "pass":
                return _reject(predicted_receipt, receipt, evaluation, predicted_root)

            finalized_mask = predicted_root / "finalized-mask.png"
            finalization = finalize_binary_mask(
                draft_path, finalized_mask, safety_margin_pixels=5
            )
            finalized_sha256 = str(finalization["approved_sha256"])
            finalized_pixels = np.asarray(
                Image.open(finalized_mask).convert("L")
            ) == 255
            _components, finalized_component_count = label(finalized_pixels)
            metrics.update(
                finalized_visible_pixel_count=int(finalized_pixels.sum()),
                finalized_pixel_count=int(finalized_pixels.size),
                finalized_connected_component_count=int(finalized_component_count),
            )
            evaluation = evaluate_automatic_gates(metrics, fold_metrics)
            receipt["gate_evaluation"] = evaluation
            if evaluation["status"] != "pass":
                return _reject(
                    predicted_receipt, receipt, evaluation, predicted_root
                )
            evidence_paths = {
                "primary/proposal-seal.json": primary_seal,
                "primary/held-out/detection_audit_summary.json": held_out_root
                / "detection_audit_summary.json",
                "primary/held-out/point_source_audit.jsonl": held_out_root
                / "point_source_audit.jsonl",
                "primary/held-out/point_source_audit_summary.json": held_out_root
                / "point_source_audit_summary.json",
                "finalized-mask.png": finalized_mask,
            }
            for index, seal in enumerate(fold_seals):
                evidence_paths[f"fold-{index}/proposal-seal.json"] = seal
                evidence_paths[f"fold-{index}/comparison.json"] = seal.parent / "comparison.json"
            artifact_hashes = {name: _sha256(path) for name, path in evidence_paths.items()}
            code_paths = {
                "visible_sky_auto_workflow.py": Path(__file__),
                "visible_sky_automatic.py": Path(__file__).with_name("visible_sky_automatic.py"),
                "visible_sky_calibration.py": Path(__file__).with_name("visible_sky_calibration.py"),
                "visible_sky_registry.py": Path(__file__).with_name("visible_sky_registry.py"),
                "scripts/replay_visible_sky_cold_start.py": Path(__file__).parent
                / "scripts/replay_visible_sky_cold_start.py",
                "SOURCE_MANIFEST.json": Path(__file__).with_name("SOURCE_MANIFEST.json"),
            }
            code_hashes = {name: _sha256(path) for name, path in code_paths.items()}
            detector_signature_sha256 = hashlib.sha256(
                json.dumps(asdict(signature), sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            acceptance = canonical_acceptance_payload(
                identity={
                    "source_id": config.source_id,
                    "camera_id": config.camera_id,
                    "installation_id": config.installation_id,
                    "orientation": config.orientation,
                    "detector_signature_sha256": detector_signature_sha256,
                },
                sources=[_source_payload(source) for source in sources],
                metrics=metrics,
                fold_metrics=fold_metrics,
                artifact_sha256=artifact_hashes,
                code_sha256=code_hashes,
                finalized_mask_sha256=finalized_sha256,
            )
            acceptance_sha256 = canonical_json_sha256(acceptance)
            acceptance_path = (
                config.calibration_root
                / "automatic-acceptance"
                / config.installation_id
                / f"{acceptance_sha256}.json"
            )
            if acceptance_path.exists():
                if _sha256(acceptance_path) != acceptance_sha256:
                    raise ValueError("existing canonical acceptance checksum mismatch")
            else:
                atomic_write_json(acceptance_path, acceptance)
            if _sha256(acceptance_path) != acceptance_sha256:
                raise ValueError("published canonical acceptance checksum mismatch")
            receipt["stages"].append("acceptance")

            mask_id = automatic_mask_id(
                config.installation_id, finalized_sha256, acceptance_sha256
            )
            existing_manifest = (
                config.calibration_root
                / config.installation_id
                / mask_id
                / f"{mask_id}.json"
            )
            if existing_manifest.is_file():
                manifest_path = existing_manifest
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                if existing.get("mask_sha256") != finalized_sha256:
                    raise ValueError("existing automatic manifest mask checksum mismatch")
                evidence = existing.get("approval", {}).get("automatic_acceptance", {})
                if evidence.get("sha256") != acceptance_sha256:
                    raise ValueError("existing automatic manifest acceptance mismatch")
            else:
                manifest_path = approve_proposal(
                    primary_root / "selection.json",
                    config.calibration_root,
                    reviewed_draft_sha256=selection["artifacts"][draft_path.name],
                    mask_id=mask_id,
                    approved_by="wide-field-solver-v25-auto",
                    safety_margin_pixels=5,
                    approval_mode="automated_validation",
                    automatic_acceptance_path=acceptance_path,
                    automatic_acceptance_sha256=acceptance_sha256,
                )
            if json.loads(manifest_path.read_text(encoding="utf-8"))["mask_sha256"] != finalized_sha256:
                raise ValueError("approved automatic mask differs from validated finalization")
            receipt["stages"].append("approval")

            _verify_acceptance_inputs(
                [primary_seal, *fold_seals],
                [_source_payload(source) for source in split.holdout_sources],
                held_out_root,
                finalized_mask,
                finalized_sha256,
                acceptance_path,
                acceptance_sha256,
                evidence_paths,
                code_paths,
                metrics,
                fold_metrics,
            )
            registration = register_calibration(
                registry_path,
                manifest_path,
                source_id=config.source_id,
                camera_id=config.camera_id,
            )
            registered = True
            receipt["stages"].append("registration")

            already_active = (
                prior_active is not None
                and prior_active["installation_id"] == config.installation_id
                and prior_active["mask_id"] == mask_id
            )
            if not already_active:
                activate_installation(
                    registry_path,
                    source_id=config.source_id,
                    camera_id=config.camera_id,
                    installation_id=config.installation_id,
                    mask_id=mask_id,
                )
            activated = True
            receipt["stages"].append("activation")
            receipt.update(
                status="activated",
                exit_code=0,
                automatic_acceptance_path=str(acceptance_path),
                automatic_acceptance_sha256=acceptance_sha256,
                manifest_path=str(manifest_path),
                manifest_sha256=_sha256(manifest_path),
                mask_id=mask_id,
                mask_sha256=finalized_sha256,
                registration=registration,
            )
            atomic_write_json(predicted_receipt, receipt)
            return AutomaticWorkflowResult(
                "activated", 0, predicted_root, predicted_receipt, manifest_path
            )
        except Exception as exc:
            if activated:
                return AutomaticWorkflowResult(
                    "activated", 0, predicted_root, predicted_receipt, manifest_path
                )
            receipt.update(
                status="operational_failure",
                exit_code=3,
                error_type=type(exc).__name__,
                error=str(exc),
                partial_state="registered_inactive" if registered else "not_registered",
                manifest_path=str(manifest_path) if manifest_path else None,
            )
            try:
                atomic_write_json(predicted_receipt, receipt)
            except Exception:
                pass
            return AutomaticWorkflowResult(
                "operational_failure", 3, predicted_root, predicted_receipt, manifest_path
            )
