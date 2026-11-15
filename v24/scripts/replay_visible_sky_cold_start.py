#!/usr/bin/env python3
"""Create and evaluate a sealed cold-start visible-sky mask proposal."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Sequence

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
    verified_sources_from_manifest,
)


SEAL_SCHEMA = "wide-field-solver-visible-sky-cold-start-seal-v1"
SPLIT_SCHEMA = "wide-field-solver-visible-sky-cold-start-split-v1"
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
    frames = []
    records = []
    displays = []
    for source in split.selected_calibration_sources:
        frame, record, display = load_native_luminance(source.path)
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
        source_id=args.source,
        camera_id=args.camera,
        installation_id=args.installation_id,
        orientation=args.orientation,
        detector_signature=asdict(signature),
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
    _write_json(output / "date-split.json", split_payload)
    shutil.copy2(output / "boundary_review.png", output / "cold_start_boundary_review.png")
    shutil.copy2(
        output / "boundary_review_inverted.png",
        output / "cold_start_boundary_review_inverted.png",
    )
    return create_proposal_seal(output)


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
        frame, _loaded, display = load_native_luminance(path)
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
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
