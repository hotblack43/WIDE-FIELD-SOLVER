#!/usr/bin/env python3
"""Create and evaluate a sealed cold-start visible-sky mask proposal."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import csv
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Mapping, Sequence

import numpy as np
from astropy.io import fits
from PIL import Image
from scipy.ndimage import binary_erosion, distance_transform_edt

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

if __package__:
    from .build_visible_sky_mask import (
        _review_overlay,
        accumulate_temporal_evidence,
        load_native_luminance,
        propose_visible_sky,
        robust_normalize,
        write_proposal,
    )
else:
    from build_visible_sky_mask import (
        _review_overlay,
        accumulate_temporal_evidence,
        load_native_luminance,
        propose_visible_sky,
        robust_normalize,
        write_proposal,
    )

from point_star_footprint import infer_sky_footprint
from point_star_detection import detect_stars
from point_star_image import load_scientific_image
from visible_sky_calibration import (
    DetectorSignature,
    artifact_inventory_sha256,
    detector_signature,
    partition_dates,
    require_single_detector_signature,
    select_phase_cycled_sources,
    verified_sources_from_manifest,
)


SEAL_SCHEMA = "wide-field-solver-visible-sky-cold-start-seal-v1"
SPLIT_SCHEMA = "wide-field-solver-visible-sky-cold-start-split-v1"
ACCEPTANCE_SCHEMA = "wide-field-solver-visible-sky-cold-start-acceptance-v1"
MMTO_ACCEPTANCE_ID = "mmto-visible-sky-cold-start-20261115-native-v1"
MMTO_ACCEPTANCE_SCOPE = (
    "MMTO camera-installation cold-start reproducibility; not cross-camera validation"
)
MMTO_ACCEPTANCE_PROPOSAL_SEAL_SHA256 = (
    "08207d2758c02138c5d5c590fb29255f883f58461177a7b1b38fe025fde03423"
)
MMTO_ACCEPTANCE_REFERENCE = {
    "manifest_sha256": "383dd5f2f212f1035d71612970a3456496c3c4f4c11ad3edacea6e3b37f4f904",
    "mask_id": "mmto-visible-sky-2026a-v1",
    "mask_sha256": "996e27f13cb726c8b759fca641c05b7937325ebd81e297db2f06de17f48cd144",
}
MMTO_ACCEPTANCE_EVIDENCE_SHA256 = {
    "approved_comparison.png": "7f90983b8046a9fa5355b1b27a4088227d67fd71a1d1156f54e03b4932b34129",
    "cold_start_boundary_review.png": "0c53bf1c96f377da7b13a4f7ccd549ad7cbbeb6ed8eb09f31e9a303cd2be3f65",
    "cold_start_boundary_review_inverted.png": "c0f89e67afb68763ecfefdb0c3ef79287d3953031e8dd8599276acae70701584",
    "comparison.json": "0eee5dffc417fb5eb7692bcda4f4fc2a420d1d72421e8763565a5e6a5ca95a98",
    "point_source_audit_summary.json": "2a9b8fbeced6a7190fc39b59cfff80f75a45bb34c1067a4f83ad66d9cb9cf284",
    "proposal-seal.json": MMTO_ACCEPTANCE_PROPOSAL_SEAL_SHA256,
    "selection.json": "24ca1fcf55216bd54696af3892d4bd9e6498e8f557daf358d31a3f4cddc37dc8",
}
MMTO_ACCEPTANCE_THRESHOLDS = {
    "boundary_distance_mean_pixels": {"maximum": 6.5},
    "boundary_distance_p95_pixels": {"maximum": 16.0},
    "exact_pixel_agreement": {"minimum": 0.98},
    "false_excluded_fraction": {"maximum": 0.005},
    "false_visible_fraction": {"maximum": 0.015},
    "intersection_over_union": {"minimum": 0.97},
}
FIXED_ACCEPTANCE_BASELINES = {
    MMTO_ACCEPTANCE_ID: {
        "scope": MMTO_ACCEPTANCE_SCOPE,
        "proposal_seal_sha256": MMTO_ACCEPTANCE_PROPOSAL_SEAL_SHA256,
        "approved_reference": MMTO_ACCEPTANCE_REFERENCE,
        "evidence_sha256": MMTO_ACCEPTANCE_EVIDENCE_SHA256,
        "thresholds": MMTO_ACCEPTANCE_THRESHOLDS,
    }
}
DEFAULT_ACCEPTANCE_RECEIPT = (
    PACKAGE_ROOT / "examples/mmto/cold_start_regression_acceptance.json"
)
_AUDIT_PROPOSAL: np.ndarray | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def create_proposal_seal(output: Path) -> Path:
    root = Path(output).expanduser().resolve(strict=True)
    seal_path = root / "proposal-seal.json"
    if seal_path.exists():
        raise FileExistsError(seal_path)
    artifacts = {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path != seal_path
    }
    if not artifacts:
        raise ValueError("cold-start proposal has no artifacts to seal")
    payload = {
        "schema": SEAL_SCHEMA,
        "status": "sealed_before_reference_reveal",
        "artifacts": artifacts,
        "artifact_inventory_sha256": artifact_inventory_sha256(artifacts),
    }
    _write_json(seal_path, payload)
    return seal_path


def verify_proposal_seal(seal_path: Path) -> dict[str, object]:
    path = Path(seal_path).expanduser().resolve(strict=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SEAL_SCHEMA or payload.get("status") != "sealed_before_reference_reveal":
        raise ValueError(f"invalid cold-start proposal seal: {path}")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("cold-start proposal seal has no artifact inventory")
    if payload.get("artifact_inventory_sha256") != artifact_inventory_sha256(artifacts):
        raise ValueError("cold-start proposal artifact inventory checksum mismatch")
    for relative, expected in artifacts.items():
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError(f"invalid sealed artifact path: {relative!r}")
        artifact = path.parent / relative
        if not artifact.is_file():
            raise FileNotFoundError(f"sealed proposal artifact is missing: {artifact}")
        observed = _sha256(artifact)
        if observed != expected:
            raise ValueError(f"sealed proposal artifact checksum mismatch: {artifact}")
    return payload


def _boundary(mask: np.ndarray) -> np.ndarray:
    values = np.asarray(mask, dtype=bool)
    return values ^ binary_erosion(values)


def comparison_metrics(proposed: np.ndarray, approved: np.ndarray) -> dict[str, object]:
    proposal = np.asarray(proposed, dtype=bool)
    reference = np.asarray(approved, dtype=bool)
    if proposal.shape != reference.shape:
        raise ValueError(
            f"proposal/reference shape mismatch: {proposal.shape} != {reference.shape}"
        )
    intersection = proposal & reference
    union = proposal | reference
    false_visible = proposal & ~reference
    false_excluded = ~proposal & reference
    proposal_boundary = _boundary(proposal)
    reference_boundary = _boundary(reference)
    distances = []
    if proposal_boundary.any() and reference_boundary.any():
        to_reference = distance_transform_edt(~reference_boundary)
        to_proposal = distance_transform_edt(~proposal_boundary)
        distances = np.concatenate(
            (to_reference[proposal_boundary], to_proposal[reference_boundary])
        )
    return {
        "pixels": int(proposal.size),
        "matching_pixels": int((proposal == reference).sum()),
        "exact_pixel_agreement": float(np.mean(proposal == reference)),
        "intersection_pixels": int(intersection.sum()),
        "union_pixels": int(union.sum()),
        "intersection_over_union": float(intersection.sum() / union.sum())
        if union.any()
        else 1.0,
        "false_visible_pixels": int(false_visible.sum()),
        "false_visible_fraction": float(false_visible.mean()),
        "false_excluded_pixels": int(false_excluded.sum()),
        "false_excluded_fraction": float(false_excluded.mean()),
        "boundary_distance_mean_pixels": float(np.mean(distances)) if len(distances) else 0.0,
        "boundary_distance_p95_pixels": float(np.percentile(distances, 95.0))
        if len(distances)
        else 0.0,
        "boundary_distance_max_pixels": float(np.max(distances)) if len(distances) else 0.0,
    }


def check_regression_acceptance(
    comparison: dict[str, object], acceptance: dict[str, object]
) -> dict[str, object]:
    """Check one sealed comparison against a visually approved fixed baseline."""
    if (
        acceptance.get("schema") != ACCEPTANCE_SCHEMA
        or acceptance.get("status") != "accepted_regression_baseline"
        or not isinstance(acceptance.get("visual_review"), dict)
        or acceptance["visual_review"].get("decision") != "accepted"
    ):
        raise ValueError("cold-start regression acceptance is not approved")
    baseline_id = acceptance.get("baseline_id")
    fixed = FIXED_ACCEPTANCE_BASELINES.get(baseline_id)
    if fixed is None:
        raise ValueError("unknown cold-start regression acceptance baseline")
    expected_seal = fixed["proposal_seal_sha256"]
    if acceptance.get("proposal_seal_sha256") != expected_seal:
        raise ValueError("cold-start acceptance proposal seal was altered")
    if acceptance.get("scope") != fixed["scope"]:
        raise ValueError("cold-start acceptance scope was altered")
    if acceptance.get("approved_reference") != fixed["approved_reference"]:
        raise ValueError("cold-start acceptance reference was altered")
    if acceptance.get("evidence_sha256") != fixed["evidence_sha256"]:
        raise ValueError("cold-start acceptance evidence was altered")
    if acceptance.get("thresholds") != fixed["thresholds"]:
        raise ValueError("cold-start acceptance thresholds were altered")
    if comparison.get("status") != "evaluated_after_sealed_cold_start":
        raise ValueError("comparison is not a sealed cold-start evaluation")
    candidate_seal = comparison.get("proposal_seal_sha256")
    if not _is_sha256(candidate_seal):
        raise ValueError("comparison proposal seal is missing or invalid")
    candidate_seal_path = comparison.get("proposal_seal")
    if not isinstance(candidate_seal_path, str) or not candidate_seal_path:
        raise ValueError("comparison proposal seal path is missing or invalid")
    verified_seal_path = Path(candidate_seal_path).expanduser().resolve(strict=True)
    verify_proposal_seal(verified_seal_path)
    if _sha256(verified_seal_path) != candidate_seal:
        raise ValueError("comparison proposal seal checksum mismatch")
    reference = fixed["approved_reference"]
    comparison_reference = {
        "manifest_sha256": comparison.get("approved_reference_manifest_sha256"),
        "mask_id": comparison.get("approved_reference_mask_id"),
        "mask_sha256": comparison.get("approved_reference_mask_sha256"),
    }
    if comparison_reference != reference:
        raise ValueError("comparison approved reference does not match the baseline")
    metrics = comparison.get("metrics")
    thresholds = acceptance.get("thresholds")
    if not isinstance(metrics, dict) or not isinstance(thresholds, dict):
        raise ValueError("comparison metrics or acceptance thresholds are missing")
    checks = []
    failed = []
    for metric, rule in thresholds.items():
        if not isinstance(rule, dict) or set(rule) not in ({"minimum"}, {"maximum"}):
            raise ValueError(f"invalid regression threshold rule: {metric}")
        observed = metrics.get(metric)
        if (
            isinstance(observed, bool)
            or not isinstance(observed, (int, float))
            or not np.isfinite(observed)
        ):
            raise ValueError(f"missing or non-finite regression metric: {metric}")
        if "minimum" in rule:
            limit = float(rule["minimum"])
            passed = float(observed) >= limit
            relation = "minimum"
        else:
            limit = float(rule["maximum"])
            passed = float(observed) <= limit
            relation = "maximum"
        checks.append({
            "metric": metric,
            "observed": float(observed),
            "relation": relation,
            "limit": limit,
            "passed": bool(passed),
        })
        if not passed:
            failed.append(metric)
    return {
        "status": "pass" if not failed else "fail",
        "candidate_proposal_seal_sha256": candidate_seal,
        "accepted_baseline_proposal_seal_sha256": expected_seal,
        "checks": checks,
        "failed_metrics": failed,
    }


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _source_payload(source) -> dict[str, object]:
    payload = asdict(source)
    payload["path"] = str(source.path)
    return payload


def archive_detector_signature(path: Path, *, orientation: str) -> DetectorSignature:
    """Read FITS detector identity without decompressing its pixel cube."""
    source = Path(path)
    lower = source.name.lower()
    if not (lower.endswith(".fits") or lower.endswith(".fit")
            or lower.endswith(".fits.bz2") or lower.endswith(".fit.bz2")):
        return detector_signature(source, orientation=orientation)
    with fits.open(
        source,
        memmap=False,
        do_not_scale_image_data=True,
        lazy_load_hdus=True,
    ) as hdus:
        candidates = [hdu for hdu in hdus if int(hdu.header.get("NAXIS", 0)) >= 2]
        if len(candidates) != 1:
            return detector_signature(source, orientation=orientation)
        hdu = candidates[0]
        shape = tuple(int(value) for value in hdu.shape)
        instrument = str(hdu.header.get("INSTRUME", "")).strip() or None
    if len(shape) == 2:
        spatial_shape = shape
        layout = "two_dimensional"
        names = ("L",)
    elif len(shape) == 3 and shape[0] in (3, 4):
        spatial_shape = shape[1:]
        layout = "plane_first"
        names = ("R", "G", "B") if shape[0] == 3 else ("R", "G1", "G2", "B")
    elif len(shape) == 3 and shape[-1] in (3, 4):
        spatial_shape = shape[:2]
        layout = "plane_last"
        names = ("R", "G", "B") if shape[-1] == 3 else ("R", "G1", "G2", "B")
    else:
        return detector_signature(source, orientation=orientation)
    return DetectorSignature(
        spatial_shape=spatial_shape,
        channel_layout=layout,
        plane_names=names,
        instrument=instrument,
        orientation=orientation,
    )


def propose_command(args: argparse.Namespace) -> Path:
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"cold-start output already exists: {output}")
    sources = verified_sources_from_manifest(
        args.download_manifest,
        args.archive_root,
        args.source,
        args.camera,
    )
    split = partition_dates(
        sources,
        holdout_modulus=args.holdout_modulus,
        holdout_remainder=args.holdout_remainder,
    )
    signature = require_single_detector_signature(
        tuple(
            (
                source.path,
                archive_detector_signature(source.path, orientation=args.orientation),
            )
            for source in sources
        )
    )
    split_payload = {
        "schema": SPLIT_SCHEMA,
        "holdout_modulus": args.holdout_modulus,
        "holdout_remainder": args.holdout_remainder,
        "source_count": len(sources),
        "calibration_dates": list(split.calibration_dates),
        "holdout_dates": list(split.holdout_dates),
        "calibration_sources": [
            _source_payload(source) for source in split.calibration_sources
        ],
        "holdout_sources": [
            _source_payload(source) for source in split.holdout_sources
        ],
        "selected_calibration_sources": [
            _source_payload(source) for source in split.selected_calibration_sources
        ],
    }
    return create_sealed_proposal_from_sources(
        split.selected_calibration_sources,
        output=output,
        source_id=args.source,
        camera_id=args.camera,
        installation_id=args.installation_id,
        orientation=args.orientation,
        date_split_payload=split_payload,
        detector_signature_override=signature,
    )


def create_sealed_proposal_from_sources(
    sources: Sequence,
    *,
    output: Path,
    source_id: str,
    camera_id: str,
    installation_id: str,
    orientation: str,
    date_split_payload: Mapping[str, object] | None = None,
    detector_signature_override: DetectorSignature | None = None,
) -> Path:
    """Create one sealed proposal from an exact preselected source population."""
    output = Path(output).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"cold-start output already exists: {output}")
    ordered = tuple(
        sorted(
            sources,
            key=lambda source: (
                source.observation_date,
                source.observed_utc,
                source.path.name,
                str(source.path),
            ),
        )
    )
    if not ordered:
        raise ValueError("at least one preselected calibration source is required")
    if any(source.source_id != source_id or source.camera_id != camera_id for source in ordered):
        raise ValueError("proposal sources do not match the requested source and camera")
    signature = detector_signature_override or require_single_detector_signature(
        tuple(
            (
                source.path,
                archive_detector_signature(source.path, orientation=orientation),
            )
            for source in ordered
        )
    )
    frames = []
    records = []
    displays = []
    for source in ordered:
        frame, record, display = load_native_luminance(
            source.path,
            observation_date=source.observation_date,
            source_sha256=source.source_sha256,
        )
        record["observed_utc"] = source.observed_utc
        record["observed_bytes"] = source.observed_bytes
        record["remote_url"] = source.remote_url
        _normalized, normalization = robust_normalize(frame)
        record["normalization"] = normalization
        frames.append(frame)
        records.append(record)
        displays.append(display)
    evidence = accumulate_temporal_evidence(frames)
    mask, audit = propose_visible_sky(evidence)
    write_proposal(
        output,
        mask=mask,
        evidence=evidence,
        reference_rgb=displays[len(displays) // 2],
        source_records=records,
        audit=audit,
        source_id=source_id,
        camera_id=camera_id,
        installation_id=installation_id,
        orientation=orientation,
        detector_signature=asdict(signature),
    )
    if date_split_payload is None:
        dates = sorted({source.observation_date for source in ordered})
        date_split_payload = {
            "schema": SPLIT_SCHEMA,
            "split_mode": "preselected_sources_no_holdout",
            "source_count": len(ordered),
            "calibration_dates": dates,
            "holdout_dates": [],
            "calibration_sources": [_source_payload(source) for source in ordered],
            "holdout_sources": [],
            "selected_calibration_sources": [_source_payload(source) for source in ordered],
        }
    _write_json(output / "date-split.json", dict(date_split_payload))
    shutil.copy2(output / "boundary_review.png", output / "cold_start_boundary_review.png")
    shutil.copy2(
        output / "boundary_review_inverted.png",
        output / "cold_start_boundary_review_inverted.png",
    )
    return create_proposal_seal(output)


def calibration_date_folds(
    sources: Sequence, *, fold_count: int = 5
) -> tuple[tuple, ...]:
    """Return deterministic training populations omitting disjoint date folds."""
    if fold_count != 5:
        raise ValueError("automatic acceptance requires exactly five folds")
    ordered = tuple(
        sorted(
            sources,
            key=lambda source: (
                source.observation_date,
                source.observed_utc,
                source.path.name,
                str(source.path),
            ),
        )
    )
    dates = tuple(sorted({source.observation_date for source in ordered}))
    if len(dates) < fold_count:
        raise ValueError("at least five calibration dates are required for folds")
    omitted_dates = tuple(
        frozenset(date for index, date in enumerate(dates) if index % fold_count == fold)
        for fold in range(fold_count)
    )
    return tuple(
        select_phase_cycled_sources(
            tuple(
                source
                for source in ordered
                if source.observation_date not in omitted
            )
        )
        for omitted in omitted_dates
    )


def _verify_held_out_source(record: dict[str, object]) -> Path:
    path = Path(str(record["path"])).expanduser().resolve(strict=True)
    if path.stat().st_size != int(record["observed_bytes"]):
        raise ValueError(f"held-out source size mismatch: {path}")
    if _sha256(path) != record["source_sha256"]:
        raise ValueError(f"held-out source checksum mismatch: {path}")
    return path


def _classify_mask_supports(
    detections: Sequence[dict[str, object]], proposal: np.ndarray
) -> list[dict[str, object]]:
    """Classify unmasked production detections against the proposed static mask."""
    height, width = proposal.shape
    answer = []
    for source in detections:
        x = int(np.clip(round(float(source["x_px"])), 0, width - 1))
        y = int(np.clip(round(float(source["y_px"])), 0, height - 1))
        half = int(source["measurement_half_window_px"])
        x0, x1 = max(0, x - half), min(width, x + half + 1)
        y0, y1 = max(0, y - half), min(height, y + half + 1)
        support = proposal[y0:y1, x0:x1]
        if support.all():
            status = "accepted_visible_support"
        elif support.any():
            status = "rejected_boundary_intersection"
        else:
            status = "rejected_excluded_support"
        answer.append({
            "detection_id": int(source["detection_id"]),
            "x_px": float(source["x_px"]),
            "y_px": float(source["y_px"]),
            "support_x_min": x0,
            "support_x_max_exclusive": x1,
            "support_y_min": y0,
            "support_y_max_exclusive": y1,
            "support_half_window_px": half,
            "mask_status": status,
        })
    return answer


def _init_audit_worker(proposal: np.ndarray) -> None:
    global _AUDIT_PROPOSAL
    _AUDIT_PROPOSAL = np.asarray(proposal, dtype=bool)


def _audit_one_record(record: dict[str, object]) -> dict[str, object]:
    if _AUDIT_PROPOSAL is None:
        raise RuntimeError("point-source audit worker has no proposal mask")
    proposal = _AUDIT_PROPOSAL
    path = _verify_held_out_source(record)
    scientific = load_scientific_image(path)
    valid = None if scientific.valid_mask.all() else scientific.valid_mask
    unmasked, _unmasked_audit = detect_stars(
        scientific.luminance,
        valid_mask=valid,
        saturated_mask=scientific.saturated_mask,
        saturation_known=scientific.provenance()["saturation_known"],
    )
    classified = _classify_mask_supports(unmasked, proposal)
    excluded = sum(
        row["mask_status"] == "rejected_excluded_support" for row in classified
    )
    boundary = sum(
        row["mask_status"] == "rejected_boundary_intersection" for row in classified
    )
    accepted = len(classified) - excluded - boundary
    return {
        "path": str(path),
        "source_sha256": record["source_sha256"],
        "observation_date": record["observation_date"],
        "unmasked_detection_count": len(unmasked),
        "accepted_visible_support_count": accepted,
        "rejected_excluded_support_count": excluded,
        "rejected_boundary_intersection_count": boundary,
        "visible_sky_sources_rejected": excluded + boundary,
        "sources": classified,
    }


def _point_source_audit(
    records: Sequence[dict[str, object]], proposal: np.ndarray, destination: Path,
    *, workers: int | None = None,
) -> dict[str, object]:
    detail_path = destination / "point_source_audit.jsonl"
    summary_path = destination / "point_source_audit_summary.json"
    if summary_path.exists():
        raise FileExistsError(summary_path)
    worker_count = workers or min(8, os.cpu_count() or 1)
    if worker_count <= 0:
        raise ValueError("point-source audit workers must be positive")
    frame_rows = []
    if detail_path.exists():
        for line_number, line in enumerate(
            detail_path.read_text(encoding="utf-8").splitlines(), 1
        ):
            try:
                frame_rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid interrupted point-source audit at "
                    f"{detail_path}:{line_number}"
                ) from exc
        expected_prefix = [row["source_sha256"] for row in records[:len(frame_rows)]]
        observed_prefix = [row.get("source_sha256") for row in frame_rows]
        if observed_prefix != expected_prefix:
            raise ValueError("interrupted point-source audit is not the expected prefix")
    remaining = records[len(frame_rows):]
    with ProcessPoolExecutor(
        max_workers=worker_count,
        initializer=_init_audit_worker,
        initargs=(proposal,),
    ) as executor, detail_path.open("a", encoding="utf-8") as stream:
        for frame in executor.map(_audit_one_record, remaining, chunksize=1):
            stream.write(json.dumps(frame, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            frame_rows.append(frame)
    summary = {
        "status": "sealed_proposal_held_out_point_sources_audited",
        "frame_count": len(frame_rows),
        "unmasked_detection_count": sum(row["unmasked_detection_count"] for row in frame_rows),
        "accepted_visible_support_count": sum(
            row["accepted_visible_support_count"] for row in frame_rows
        ),
        "rejected_excluded_support_count": sum(
            row["rejected_excluded_support_count"] for row in frame_rows
        ),
        "rejected_boundary_intersection_count": sum(
            row["rejected_boundary_intersection_count"] for row in frame_rows
        ),
        "visible_sky_sources_rejected": sum(
            row["visible_sky_sources_rejected"] for row in frame_rows
        ),
        "detail_file": detail_path.name,
    }
    _write_json(summary_path, summary)
    return summary


def verify_completed_point_source_audit(
    records: Sequence[dict[str, object]], destination: Path
) -> dict[str, object]:
    """Revalidate the completed JSONL and summary before gate construction."""
    root = Path(destination).expanduser().resolve(strict=True)
    detail_path = root / "point_source_audit.jsonl"
    summary_path = root / "point_source_audit_summary.json"
    if not detail_path.is_file() or not summary_path.is_file():
        raise FileNotFoundError("completed point-source audit artifacts are missing")
    rows = []
    for line_number, line in enumerate(detail_path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid point-source audit detail at {detail_path}:{line_number}"
            ) from exc
    if len(rows) != len(records):
        raise ValueError(
            f"point-source audit detail row count mismatch: {len(rows)} != {len(records)}"
        )
    expected = [record.get("source_sha256") for record in records]
    observed = [row.get("source_sha256") for row in rows]
    if observed != expected:
        raise ValueError("point-source audit details are not the expected source sequence")
    required_counts = (
        "unmasked_detection_count",
        "accepted_visible_support_count",
        "rejected_excluded_support_count",
        "rejected_boundary_intersection_count",
        "visible_sky_sources_rejected",
    )
    for ordinal, row in enumerate(rows):
        for key in required_counts:
            value = row.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"invalid {key} in point-source audit detail row {ordinal}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("frame_count") != len(rows):
        raise ValueError("point-source audit summary frame count mismatch")
    for key in required_counts:
        if summary.get(key) != sum(row[key] for row in rows):
            raise ValueError(f"point-source audit summary {key} mismatch")
    return summary


def _held_out_evaluation(root: Path, proposal: np.ndarray) -> dict[str, object]:
    split = json.loads((root / "date-split.json").read_text(encoding="utf-8"))
    records = split.get("holdout_sources")
    if not isinstance(records, list) or not records:
        raise ValueError("cold-start split has no held-out sources")
    destination = root / "held-out"
    destination.mkdir(parents=False, exist_ok=False)
    grouped: dict[str, list[dict[str, object]]] = {}
    for record in records:
        grouped.setdefault(str(record["observation_date"]), []).append(record)
    overlay_paths = {
        str(sorted(members, key=lambda row: str(row["observed_utc"]))[len(members) // 2]["path"])
        for members in grouped.values()
    }
    rows = []
    for record in records:
        path = _verify_held_out_source(record)
        frame, _loaded, display = load_native_luminance(
            path,
            observation_date=str(record["observation_date"]),
            source_sha256=str(record["source_sha256"]),
        )
        normalized, normalization = robust_normalize(frame)
        footprint, footprint_audit = infer_sky_footprint(normalized * 255.0)
        intersection = footprint & proposal
        union = footprint | proposal
        row = {
            "path": str(path),
            "source_sha256": record["source_sha256"],
            "observation_date": record["observation_date"],
            "observed_utc": record["observed_utc"],
            "finite_fraction": normalization["finite_fraction"],
            "proposal_visible_median": float(np.median(normalized[proposal])),
            "proposal_excluded_median": float(np.median(normalized[~proposal])),
            "footprint_status": footprint_audit["status"],
            "footprint_intersection_pixels": int(intersection.sum()),
            "footprint_union_pixels": int(union.sum()),
            "footprint_iou_with_proposal": float(intersection.sum() / union.sum())
            if union.any()
            else 1.0,
        }
        rows.append(row)
        if str(path) in overlay_paths:
            stem = f"{record['observation_date']}_{str(record['source_sha256'])[:12]}"
            Image.fromarray(
                _review_overlay(display, proposal, inverted=False), mode="RGB"
            ).save(destination / f"{stem}_boundary.png")
            Image.fromarray(
                _review_overlay(display, proposal, inverted=True), mode="RGB"
            ).save(destination / f"{stem}_boundary_inverted.png")
    fieldnames = list(rows[0])
    with (destination / "held_out_audit.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    point_sources = _point_source_audit(records, proposal, destination)
    footprint_ratios = sorted(
        Fraction(row["footprint_intersection_pixels"], row["footprint_union_pixels"])
        for row in rows
        if row["footprint_union_pixels"] > 0
    )
    if len(footprint_ratios) != len(rows):
        raise ValueError("held-out footprint union is empty")
    middle = len(footprint_ratios) // 2
    median_ratio = (
        footprint_ratios[middle]
        if len(footprint_ratios) % 2
        else (footprint_ratios[middle - 1] + footprint_ratios[middle]) / 2
    )
    minimum_ratio = footprint_ratios[0]
    summary = {
        "status": "held_out_processed_before_reference_reveal",
        "source_count": len(rows),
        "date_count": len(grouped),
        "footprint_iou_median": float(
            np.median([row["footprint_iou_with_proposal"] for row in rows])
        ),
        "footprint_iou_minimum": float(
            np.min([row["footprint_iou_with_proposal"] for row in rows])
        ),
        "footprint_iou_median_ratio": {
            "numerator": median_ratio.numerator,
            "denominator": median_ratio.denominator,
        },
        "footprint_iou_minimum_ratio": {
            "numerator": minimum_ratio.numerator,
            "denominator": minimum_ratio.denominator,
        },
        "overlay_count": len(overlay_paths),
        "point_sources": point_sources,
    }
    _write_json(destination / "detection_audit_summary.json", summary)
    return summary


def audit_held_out_command(args: argparse.Namespace) -> Path:
    seal_path = args.proposal_seal.expanduser().resolve(strict=True)
    verify_proposal_seal(seal_path)
    root = seal_path.parent
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    drafts = [name for name in selection["artifacts"] if name.endswith(".draft.png")]
    if len(drafts) != 1:
        raise ValueError("sealed proposal does not identify exactly one draft mask")
    proposal = np.asarray(Image.open(root / drafts[0]).convert("L")) == 255
    split = json.loads((root / "date-split.json").read_text(encoding="utf-8"))
    records = split.get("holdout_sources")
    if not isinstance(records, list) or not records:
        raise ValueError("cold-start split has no held-out sources")
    summary = _point_source_audit(
        records, proposal, root / "held-out", workers=args.workers
    )
    return root / "held-out" / "point_source_audit_summary.json"


def _load_approved_reference(manifest_path: Path) -> tuple[np.ndarray, dict[str, object]]:
    path = Path(manifest_path).expanduser().resolve(strict=True)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("status") != "approved":
        raise ValueError("reference manifest is not approved")
    mask_path = path.parent / str(manifest["mask_file"])
    if _sha256(mask_path) != manifest.get("mask_sha256"):
        raise ValueError("approved reference mask checksum mismatch")
    pixels = np.asarray(Image.open(mask_path).convert("L"))
    if not np.isin(pixels, (0, 255)).all():
        raise ValueError("approved reference mask is not binary")
    return pixels == 255, manifest


def _comparison_image(proposal: np.ndarray, approved: np.ndarray) -> np.ndarray:
    panels = []
    for mask in (proposal, approved):
        grey = np.where(mask, 235, 25).astype(np.uint8)
        panels.append(np.repeat(grey[..., None], 3, axis=2))
    difference = np.zeros((*proposal.shape, 3), dtype=np.uint8)
    difference[~proposal & ~approved] = (25, 25, 25)
    difference[proposal & approved] = (220, 220, 220)
    difference[proposal & ~approved] = (230, 45, 45)
    difference[~proposal & approved] = (45, 105, 230)
    panels.append(difference)
    separator = np.full((proposal.shape[0], 4, 3), 255, dtype=np.uint8)
    return np.concatenate((panels[0], separator, panels[1], separator, panels[2]), axis=1)


def evaluate_command(args: argparse.Namespace) -> Path:
    seal_path = args.proposal_seal.expanduser().resolve(strict=True)
    verify_proposal_seal(seal_path)
    root = seal_path.parent
    selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    drafts = [name for name in selection["artifacts"] if name.endswith(".draft.png")]
    if len(drafts) != 1:
        raise ValueError("sealed proposal does not identify exactly one draft mask")
    proposal_pixels = np.asarray(Image.open(root / drafts[0]).convert("L"))
    if not np.isin(proposal_pixels, (0, 255)).all():
        raise ValueError("sealed proposal draft is not binary")
    proposal = proposal_pixels == 255

    held_out = _held_out_evaluation(root, proposal)

    approved, manifest = _load_approved_reference(args.approved_reference_manifest)
    metrics = comparison_metrics(proposal, approved)
    comparison = {
        "status": "evaluated_after_sealed_cold_start",
        "proposal_seal": str(seal_path),
        "proposal_seal_sha256": _sha256(seal_path),
        "approved_reference_manifest": str(
            args.approved_reference_manifest.expanduser().resolve(strict=True)
        ),
        "approved_reference_mask_id": manifest.get("mask_id"),
        "approved_reference_manifest_sha256": _sha256(
            args.approved_reference_manifest.expanduser().resolve(strict=True)
        ),
        "approved_reference_mask_sha256": manifest.get("mask_sha256"),
        "held_out": held_out,
        "metrics": metrics,
    }
    comparison_path = root / "comparison.json"
    _write_json(comparison_path, comparison)
    with (root / "comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(metrics))
        writer.writeheader()
        writer.writerow(metrics)
    Image.fromarray(_comparison_image(proposal, approved), mode="RGB").save(
        root / "approved_comparison.png"
    )
    return comparison_path


def check_acceptance_command(args: argparse.Namespace) -> dict[str, object]:
    comparison_path = args.comparison.expanduser().resolve(strict=True)
    acceptance_path = args.acceptance.expanduser().resolve(strict=True)
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    return check_regression_acceptance(comparison, acceptance)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    propose = commands.add_parser(
        "propose", help="create and seal a cold-start proposal without a reference"
    )
    propose.add_argument("--download-manifest", type=Path, required=True)
    propose.add_argument("--archive-root", type=Path, required=True)
    propose.add_argument("--source", required=True)
    propose.add_argument("--camera", required=True)
    propose.add_argument("--installation-id", required=True)
    propose.add_argument("--orientation", required=True)
    propose.add_argument("--holdout-modulus", type=int, default=5)
    propose.add_argument("--holdout-remainder", type=int, default=0)
    propose.add_argument("--output", type=Path, required=True)
    evaluate = commands.add_parser(
        "evaluate", help="verify a seal, process held-out data, then reveal a reference"
    )
    evaluate.add_argument("--proposal-seal", type=Path, required=True)
    evaluate.add_argument("--approved-reference-manifest", type=Path, required=True)
    audit = commands.add_parser(
        "audit-held-out",
        help="add production point-source evidence to an existing sealed replay",
    )
    audit.add_argument("--proposal-seal", type=Path, required=True)
    audit.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    check = commands.add_parser(
        "check-acceptance",
        help="enforce a visually accepted fixed regression baseline",
    )
    check.add_argument("--comparison", type=Path, required=True)
    check.add_argument(
        "--acceptance",
        type=Path,
        default=DEFAULT_ACCEPTANCE_RECEIPT,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "propose":
        print(propose_command(args))
        return 0
    if args.command == "evaluate":
        print(evaluate_command(args))
        return 0
    if args.command == "audit-held-out":
        print(audit_held_out_command(args))
        return 0
    if args.command == "check-acceptance":
        result = check_acceptance_command(args)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "pass" else 1
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
