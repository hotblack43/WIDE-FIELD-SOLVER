#!/usr/bin/env python3
"""Build review-only temporal evidence for an installation sky mask."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable, Sequence

import numpy as np
from PIL import Image
from scipy.ndimage import (
    binary_closing,
    binary_erosion,
    gaussian_filter,
    label,
    maximum_filter,
    minimum_filter1d,
    sobel,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from point_star_footprint import infer_sky_footprint
from point_star_image import load_scientific_image, report_display_rgb


DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTALLATION_DRAFT_NAME = "mmto_installation_2026a.draft.png"


@dataclass(frozen=True)
class TemporalEvidence:
    temporal_median: np.ndarray
    temporal_variability: np.ndarray
    edge_persistence: np.ndarray
    source_density: np.ndarray
    optical_consensus: np.ndarray
    frame_count: int


def _observation_date(path: Path) -> str:
    for parent in path.parents:
        if DATE_PATTERN.match(parent.name):
            date.fromisoformat(parent.name)
            return parent.name
    match = re.match(r"(\d{4})_(\d{2})_(\d{2})", path.name)
    if match:
        value = "-".join(match.groups())
        date.fromisoformat(value)
        return value
    raise ValueError(f"cannot determine observing date from {path}")


def select_representative_sources(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Select one deterministic early/middle/late-phase frame per date."""
    grouped: dict[str, list[Path]] = {}
    for raw in paths:
        path = Path(raw)
        grouped.setdefault(_observation_date(path), []).append(path)
    phases = (0.25, 0.50, 0.75)
    selected = []
    for ordinal, (_night, members) in enumerate(sorted(grouped.items())):
        members = sorted(members, key=lambda item: (item.name, str(item)))
        index = round(phases[ordinal % len(phases)] * (len(members) - 1))
        selected.append(members[index])
    return tuple(selected)


def load_native_luminance(path: Path):
    """Load native scientific samples and retain a display-only RGB view."""
    image = load_scientific_image(path)
    metadata = image.provenance()
    record = {
        "path": str(image.path),
        "source_sha256": metadata["source_sha256"],
        "spatial_shape": list(image.shape),
        "decoded_dtype": metadata["decoded_dtype"],
        "channel_layout": metadata["channel_layout"],
        "plane_names": metadata["plane_names"],
        "observation_date": _observation_date(image.path),
    }
    return (
        np.asarray(image.luminance, dtype=float),
        record,
        report_display_rgb(image),
    )


def robust_normalize(frame: np.ndarray):
    """Map a native frame to finite 1--99 percentile display coordinates."""
    values = np.asarray(frame, dtype=float)
    finite = np.isfinite(values)
    if values.ndim != 2 or not finite.any():
        raise ValueError("each source must provide a finite two-dimensional image")
    low, high = np.percentile(values[finite], [1.0, 99.0])
    if high <= low:
        high = low + 1.0
    normalized = np.zeros(values.shape, dtype=np.float32)
    normalized[finite] = np.clip((values[finite] - low) / (high - low), 0.0, 1.0)
    return normalized, {
        "method": "finite_1_99_percentile_linear_clip",
        "low_native": float(low),
        "high_native": float(high),
        "finite_fraction": float(finite.mean()),
    }


def _unit_scale(values: np.ndarray, percentile: float = 99.0) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32)
    finite = np.isfinite(array)
    ceiling = float(np.percentile(array[finite], percentile)) if finite.any() else 0.0
    if ceiling <= 0.0:
        return np.zeros(array.shape, dtype=np.float32)
    return np.clip(array / ceiling, 0.0, 1.0).astype(np.float32)


def _source_peaks(frame: np.ndarray) -> np.ndarray:
    values = np.asarray(frame, dtype=float)
    finite = np.isfinite(values)
    low, high = np.percentile(values[finite], [1.0, 99.99])
    if high <= low:
        high = low + 1.0
    scaled = np.zeros(values.shape, dtype=np.float32)
    scaled[finite] = np.clip((values[finite] - low) / (high - low), 0.0, 1.0)
    sigma = max(1.2, min(frame.shape) / 300.0)
    residual = scaled - gaussian_filter(scaled, sigma=sigma)
    median = float(np.median(residual))
    mad = float(np.median(np.abs(residual - median)))
    threshold = median + max(0.015, 7.0 * 1.4826 * mad)
    local = maximum_filter(residual, size=5, mode="nearest")
    return (residual == local) & (residual > threshold)


def accumulate_temporal_evidence(frames: Sequence[np.ndarray]) -> TemporalEvidence:
    """Combine normalized intensity, edge, source, and footprint evidence."""
    if len(frames) < 3:
        raise ValueError("at least three frames are required for temporal evidence")
    normalized = []
    edges = []
    peaks = []
    footprints = []
    shape = None
    for raw in frames:
        frame, _record = robust_normalize(raw)
        if shape is None:
            shape = frame.shape
        elif frame.shape != shape:
            raise ValueError(f"source shapes differ: {shape} and {frame.shape}")
        normalized.append(frame)
        gx = sobel(frame, axis=1, mode="nearest")
        gy = sobel(frame, axis=0, mode="nearest")
        magnitude = _unit_scale(np.hypot(gx, gy), 97.0)
        edges.append(magnitude > 0.18)
        peaks.append(_source_peaks(raw))
        footprint, _audit = infer_sky_footprint(frame * 255.0)
        footprints.append(footprint)
    cube = np.stack(normalized).astype(np.float32, copy=False)
    temporal_median = np.median(cube, axis=0).astype(np.float32)
    lower, upper = np.percentile(cube, [10.0, 90.0], axis=0)
    temporal_variability = _unit_scale(upper - lower, 99.0)
    edge_persistence = np.mean(np.stack(edges), axis=0, dtype=np.float32)
    source_hits = np.sum(np.stack(peaks), axis=0, dtype=np.float32)
    density_sigma = max(2.0, min(shape) / 100.0)
    source_density = _unit_scale(gaussian_filter(source_hits, density_sigma), 99.0)
    optical_consensus = np.mean(np.stack(footprints), axis=0, dtype=np.float32)
    return TemporalEvidence(
        temporal_median=temporal_median,
        temporal_variability=temporal_variability,
        edge_persistence=edge_persistence,
        source_density=source_density,
        optical_consensus=optical_consensus,
        frame_count=len(frames),
    )


def propose_visible_sky(
    evidence: TemporalEvidence,
    *,
    optical_consensus_minimum: float = 0.80,
    sky_score_minimum: float = 0.10,
):
    """Return the largest coherent sky candidate containing the image centre."""
    median_level = _unit_scale(evidence.temporal_median, 99.0)
    illuminated_variability = evidence.temporal_variability * np.sqrt(median_level)
    score = (
        0.60 * median_level
        + 0.30 * evidence.source_density
        + 0.10 * illuminated_variability
    )
    optical = evidence.optical_consensus >= optical_consensus_minimum
    candidate = optical & (score >= sky_score_minimum)
    candidate = binary_closing(candidate, iterations=2)
    local_scale = max(6.0, min(candidate.shape) / 60.0)
    local_background = gaussian_filter(median_level, sigma=local_scale)
    persistent_dark_structure = (
        optical
        & (local_background >= 0.05)
        & (median_level < 0.72 * local_background)
    )
    candidate &= ~persistent_dark_structure
    height, width = candidate.shape
    centre_x = (width - 1) / 2.0
    centre_y = (height - 1) / 2.0
    yy, xx = np.indices(candidate.shape)
    radius = np.hypot(xx - centre_x, yy - centre_y)
    angle = np.mod(np.arctan2(yy - centre_y, xx - centre_x), 2.0 * np.pi)
    radial_bin_count = max(360, round(0.25 * 2.0 * np.pi * min(candidate.shape)))
    radial_bin = np.minimum(
        (angle * radial_bin_count / (2.0 * np.pi)).astype(int),
        radial_bin_count - 1,
    )
    minimum_structure_radius = 0.20 * min(candidate.shape)
    blocker = (~optical) | (persistent_dark_structure & (radius >= minimum_structure_radius))
    skyline_radius = np.full(radial_bin_count, np.inf, dtype=float)
    np.minimum.at(skyline_radius, radial_bin[blocker], radius[blocker])
    finite_skyline = np.isfinite(skyline_radius)
    if finite_skyline.any() and not finite_skyline.all():
        known = np.flatnonzero(finite_skyline)
        missing = np.flatnonzero(~finite_skyline)
        extended_x = np.concatenate((known - radial_bin_count, known, known + radial_bin_count))
        extended_y = np.tile(skyline_radius[known], 3)
        skyline_radius[missing] = np.interp(missing, extended_x, extended_y)
    skyline_radius = minimum_filter1d(skyline_radius, size=3, mode="wrap")
    radial_sky = radius < skyline_radius[radial_bin]
    candidate &= radial_sky
    components, count = label(candidate)
    centre = (candidate.shape[0] // 2, candidate.shape[1] // 2)
    chosen = int(components[centre])
    if chosen == 0 and count:
        sizes = np.bincount(components.ravel())
        sizes[0] = 0
        chosen = int(np.argmax(sizes))
    mask = components == chosen if chosen else np.zeros(candidate.shape, dtype=bool)
    mask &= optical
    audit = {
        "method": "temporal_intensity_source_variability_connected_sky",
        "frame_count": evidence.frame_count,
        "optical_consensus_minimum": optical_consensus_minimum,
        "sky_score_minimum": sky_score_minimum,
        "local_dark_structure_ratio_maximum": 0.72,
        "local_dark_structure_scale_pixels": float(local_scale),
        "radial_skyline_bins": int(radial_bin_count),
        "minimum_structure_radius_pixels": float(minimum_structure_radius),
        "score_weights": {
            "temporal_median": 0.60,
            "source_density": 0.30,
            "illuminated_temporal_variability": 0.10,
        },
        "connected_components": int(count),
        "visible_fraction": float(mask.mean()),
        "visible_pixels": int(mask.sum()),
        "excluded_pixels": int(mask.size - mask.sum()),
        "safety_margin_pixels": 0,
        "safety_margin_status": "deferred_until_approval",
    }
    return mask.astype(bool), audit


def _reference_from_evidence(evidence: TemporalEvidence) -> np.ndarray:
    grey = np.uint8(np.rint(np.clip(evidence.temporal_median, 0.0, 1.0) * 255.0))
    return np.repeat(grey[..., None], 3, axis=2)


def _review_overlay(reference: np.ndarray, mask: np.ndarray, *, inverted: bool) -> np.ndarray:
    base = np.asarray(reference, dtype=np.uint8).copy()
    if inverted:
        base = 255 - base
    excluded = ~mask
    tint = np.array([35, 90, 225] if inverted else [220, 35, 45], dtype=float)
    base[excluded] = np.rint(0.58 * base[excluded] + 0.42 * tint).astype(np.uint8)
    boundary = mask & ~binary_erosion(mask)
    base[boundary] = np.array([255, 235, 0], dtype=np.uint8)
    return base


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finalize_approved_mask(
    draft_path: Path,
    output_path: Path,
    *,
    safety_margin_pixels: int = 5,
) -> dict[str, object]:
    """Freeze an approved draft after expanding excluded foreground inward."""
    draft_path = Path(draft_path).expanduser().resolve(strict=True)
    output_path = Path(output_path).expanduser().resolve()
    if output_path.exists():
        raise FileExistsError(output_path)
    if safety_margin_pixels < 0:
        raise ValueError("safety margin must be non-negative")
    with Image.open(draft_path) as image:
        pixels = np.asarray(image.convert("L"), dtype=np.uint8)
    values = set(np.unique(pixels).tolist())
    if not values.issubset({0, 255}):
        raise ValueError(f"draft mask must be binary 0/255, found {sorted(values)}")
    visible = pixels == 255
    approved = binary_erosion(visible, iterations=safety_margin_pixels)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.where(approved, 255, 0).astype(np.uint8), mode="L").save(output_path)
    return {
        "draft_path": str(draft_path),
        "draft_sha256": _sha256(draft_path),
        "approved_path": str(output_path),
        "approved_sha256": _sha256(output_path),
        "safety_margin_pixels": int(safety_margin_pixels),
        "draft_visible_pixels": int(visible.sum()),
        "approved_visible_pixels": int(approved.sum()),
        "excluded_pixels_added": int(visible.sum() - approved.sum()),
    }


def write_proposal(
    output: Path,
    *,
    mask: np.ndarray,
    evidence: TemporalEvidence,
    reference_rgb: np.ndarray,
    source_records: Sequence[dict[str, object]],
    audit: dict[str, object],
) -> None:
    """Write immutable review artifacts; never update an existing directory."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    binary = np.where(np.asarray(mask, dtype=bool), 255, 0).astype(np.uint8)
    reference = np.asarray(reference_rgb, dtype=np.uint8)
    if reference.shape != (*binary.shape, 3):
        reference = _reference_from_evidence(evidence)
    draft_path = output / INSTALLATION_DRAFT_NAME
    Image.fromarray(binary, mode="L").save(draft_path)
    temporal_path = output / "temporal_reference.png"
    Image.fromarray(_reference_from_evidence(evidence), mode="RGB").save(temporal_path)
    review_path = output / "boundary_review.png"
    Image.fromarray(_review_overlay(reference, mask, inverted=False), mode="RGB").save(review_path)
    inverted_path = output / "boundary_review_inverted.png"
    Image.fromarray(_review_overlay(reference, mask, inverted=True), mode="RGB").save(inverted_path)
    dates = sorted({str(record["observation_date"]) for record in source_records})
    payload = {
        "status": "draft_not_approved",
        "production_eligible": False,
        "draft_id": "mmto_installation_2026a_temporal_consensus_draft",
        "coordinate_convention": "array[y, x]; origin top-left",
        "pixel_values": {"0": "excluded", "255": "candidate visible sky"},
        "spatial_shape": list(binary.shape),
        "observation_date_coverage": {
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
            "dates": dates,
        },
        "selection": {
            "method": "one frame per date cycling early/middle/late sorted night phase",
            "source_count": len(source_records),
            "sources": list(source_records),
        },
        "normalization": "finite_1_99_percentile_linear_clip",
        "proposal": audit,
        "generation_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "artifacts": {
            draft_path.name: _sha256(draft_path),
            temporal_path.name: _sha256(temporal_path),
            review_path.name: _sha256(review_path),
            inverted_path.name: _sha256(inverted_path),
        },
    }
    (output / "selection.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _source_paths(path: Path) -> list[Path]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("sources") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise ValueError("source JSON must be a list or an object with a sources list")
    answer = []
    for entry in entries:
        raw = entry.get("path") if isinstance(entry, dict) else entry
        if not isinstance(raw, str):
            raise ValueError("each source entry must contain one path string")
        answer.append(Path(raw).expanduser().resolve())
    return answer


def propose_command(source_json: Path, output: Path) -> None:
    selected = select_representative_sources(_source_paths(source_json))
    frames = []
    records = []
    displays = []
    for path in selected:
        frame, record, display = load_native_luminance(path)
        _normalized, normalization = robust_normalize(frame)
        record["normalization"] = normalization
        frames.append(frame)
        records.append(record)
        displays.append(display)
    evidence = accumulate_temporal_evidence(frames)
    mask, audit = propose_visible_sky(evidence)
    reference = displays[len(displays) // 2]
    write_proposal(
        output,
        mask=mask,
        evidence=evidence,
        reference_rgb=reference,
        source_records=records,
        audit=audit,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    propose_parser = subparsers.add_parser("propose", help="write review-only draft products")
    propose_parser.add_argument("--sources", type=Path, required=True)
    propose_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "propose":
        propose_command(args.sources, args.output)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
