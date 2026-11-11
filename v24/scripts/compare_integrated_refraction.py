#!/usr/bin/env python3
"""Replay saved full-fisheye associations with nested robust refraction models."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path
import sqlite3
import sys
from typing import Iterable

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


PACKAGE = Path(__file__).resolve().parents[1]
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

from point_star_barghini import (
    BarghiniCamera,
    angular_block_ids,
    astrometric_stats,
    fit_camera,
    select_integrated_refraction,
    vectors,
)
from point_star_refraction import IntegratedRefraction


SUCCESS_STATUSES = {
    "point_star_fit_converged",
    "joint_epoch_adopted",
    "joint_epoch_fit_converged",
}
PRODUCT_NAMES = (
    "comparison.csv",
    "summary.json",
    "report.md",
    "integrated_refraction_comparison.png",
)


def classify_fisheye_geometry(camera: BarghiniCamera) -> dict[str, object]:
    """Classify image geometry without consulting location, time, or filenames."""
    h, w = camera.shape
    result: dict[str, object] = {
        "accepted": False,
        "shape": [int(h), int(w)],
        "aspect_ratio": float(min(h, w) / max(h, w)),
    }
    if min(h, w) < 800:
        result["reason"] = "detector_too_small"
        return result
    if result["aspect_ratio"] < 0.70:
        result["reason"] = "detector_too_narrow"
        return result

    centre = np.array([(w - 1.0) / 2.0, (h - 1.0) / 2.0])
    radius = 0.45 * min(h, w)
    phase = np.arange(16, dtype=float) * 2.0 * np.pi / 16.0
    ring = centre + np.column_stack([radius * np.cos(phase), radius * np.sin(phase)])
    rays = camera.to_sky(ring)
    dot = np.clip(rays @ rays.T, -1.0, 1.0)
    coverage = float(np.rad2deg(np.max(np.arccos(dot))))
    result["angular_diameter_deg"] = coverage
    if coverage < 120.0:
        result["reason"] = "insufficient_angular_coverage"
        return result
    result.update(accepted=True, reason="full_fisheye_geometry")
    return result


def _finite(row: dict[str, str], key: str) -> float | None:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _solution_bytes(reference: str | Path) -> tuple[bytes, bytes, str]:
    """Read exact result/coordinate products from a directory or evidence database."""
    text = str(reference)
    if text.startswith("sqlite:"):
        locator = text.removeprefix("sqlite:")
        if "#" not in locator:
            raise ValueError("SQLite references require sqlite:DATABASE#RUN_ID")
        database_name, run_id = locator.rsplit("#", 1)
        database = Path(database_name).expanduser().resolve()
        with sqlite3.connect(database) as connection:
            run = connection.execute(
                "SELECT result_json, source_path FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            coordinates = connection.execute(
                "SELECT content FROM products WHERE run_id=? AND product='star_coordinates.csv'",
                (run_id,),
            ).fetchone()
        if run is None:
            raise ValueError("run_id_not_found")
        if not run[0] or coordinates is None:
            raise ValueError("saved_products_missing")
        coordinate_content = coordinates[0]
        if isinstance(coordinate_content, str):
            coordinate_content = coordinate_content.encode()
        return str(run[0]).encode(), bytes(coordinate_content), str(run[1])
    path = Path(reference).expanduser().resolve()
    return path.read_bytes(), (path.parent / "star_coordinates.csv").read_bytes(), str(path)


def _load_solution(reference: str | Path) -> tuple[dict[str, object], BarghiniCamera, np.ndarray, np.ndarray]:
    result_bytes, coordinate_bytes, source_hint = _solution_bytes(reference)
    result = json.loads(result_bytes)
    result.setdefault("source", source_hint)
    if result.get("status") not in SUCCESS_STATUSES:
        raise ValueError("saved_solution_not_successful")
    camera = BarghiniCamera.from_serialised(result["camera"])
    rows = [row for row in csv.DictReader(coordinate_bytes.decode().splitlines())
            if row.get("usage", "fitted") == "fitted"]
    if len(rows) < 24:
        raise ValueError("insufficient_fitted_associations")
    xy: list[tuple[float, float]] = []
    radec: list[tuple[float, float]] = []
    for row in rows:
        x, y = _finite(row, "x_px"), _finite(row, "y_px")
        ra = _finite(row, "propagated_ra_deg")
        dec = _finite(row, "propagated_dec_deg")
        if ra is None or dec is None:
            ra, dec = _finite(row, "catalog_ra_deg"), _finite(row, "catalog_dec_deg")
        if x is None or y is None or ra is None or dec is None:
            raise ValueError("non_finite_fixed_association")
        xy.append((x, y))
        radec.append((ra, dec))
    radec_array = np.asarray(radec, dtype=float)
    return result, camera, np.asarray(xy, dtype=float), vectors(
        radec_array[:, 0], radec_array[:, 1])


def infer_family(result: dict[str, object], path: str | Path) -> str:
    text = f"{result.get('source', '')} {path}".lower()
    if "apicam" in text:
        return "APICAM"
    if "subaru" in text:
        return "Subaru"
    if "mmto" in text or "skycam" in text:
        return "MMTO"
    if "milky" in text or "fisheye" in text:
        return "historical"
    return "other_full_fisheye"


def _zero_camera(camera: BarghiniCamera) -> BarghiniCamera:
    return BarghiniCamera(
        camera.shape,
        camera.reference_rotation.copy(),
        camera.p.copy(),
        camera.detector_parity,
        IntegratedRefraction.zero(),
    )


def analyse_solution(path: str | Path, family: str | None = None, *, folds: int = 4,
                     max_nfev: int = 600) -> dict[str, object]:
    """Replay one fixed association set; return a row even when it fails."""
    reference = str(path)
    if not reference.startswith("sqlite:"):
        reference = str(Path(reference).expanduser().resolve())
    row: dict[str, object] = {
        "path": reference,
        "family": family or "unknown",
        "status": "failed",
        "failure_reason": "",
    }
    try:
        result, saved_camera, xy, sky = _load_solution(reference)
        row.update(
            family=family or infer_family(result, reference),
            source_sha256=str(result.get("source_sha256", "")),
            solver_version=str(result.get("solver_version", "")),
            fitted_count=int(len(xy)),
        )
        geometry = classify_fisheye_geometry(saved_camera)
        row.update(
            detector_height=int(saved_camera.shape[0]),
            detector_width=int(saved_camera.shape[1]),
            angular_diameter_deg=geometry.get("angular_diameter_deg"),
        )
        if not geometry["accepted"]:
            row.update(status="rejected_small_field", failure_reason=geometry["reason"])
            return row

        # Saved identities define this historical replay only. Both nested models
        # start with exact zero refraction and use the same robust radial objective.
        baseline, baseline_info = fit_camera(
            _zero_camera(saved_camera), xy, sky, max_nfev=max_nfev)
        candidate, candidate_info = fit_camera(
            baseline, xy, sky, max_nfev=max_nfev, fit_refraction=True)
        selected, evidence = select_integrated_refraction(
            baseline, xy, sky, candidate=candidate, folds=folds,
            max_nfev=max_nfev, candidate_info=candidate_info)
        baseline_stats = astrometric_stats(baseline, xy, sky)
        candidate_stats = astrometric_stats(candidate, xy, sky)
        selected_stats = astrometric_stats(selected, xy, sky)
        row.update(
            status="adopted" if evidence["adopted"] else "rejected_zero",
            failure_reason=evidence.get("rejection_reason", ""),
            robust_loss=baseline_info["robust_loss"],
            candidate_robust_loss=candidate_info["robust_loss"],
            fold_count=int(evidence.get("fold_count", folds)),
            improved_fold_count=int(evidence.get("improved_fold_count", 0)),
            validation_improvement_fraction=float(
                evidence.get("validation_improvement_fraction", 0.0)),
            baseline_rms_arcmin=float(baseline_stats["rms_arcmin"]),
            candidate_rms_arcmin=float(candidate_stats["rms_arcmin"]),
            selected_rms_arcmin=float(selected_stats["rms_arcmin"]),
            refraction_a_arcsec=float(candidate.refraction.refraction_a_arcsec),
            refraction_b_arcsec=float(candidate.refraction.refraction_b_arcsec),
            refraction_status=selected.refraction.status,
            physical_checks=json.dumps(evidence.get("physical_checks", {}), sort_keys=True),
        )
    except Exception as error:  # Batch evidence must retain every failed input.
        row["failure_reason"] = f"{type(error).__name__}: {error}"
    return row


def _json_safe(value: object) -> object:
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_products(rows: Iterable[dict[str, object]], output: Path) -> list[Path]:
    rows = [{key: _json_safe(value) for key, value in row.items()} for row in rows]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    products = [output / name for name in PRODUCT_NAMES]
    existing = [path for path in products if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite existing products: {existing}")

    preferred = [
        "family", "source_sha256", "path", "status", "failure_reason",
        "fitted_count", "detector_height", "detector_width", "angular_diameter_deg",
        "robust_loss", "baseline_rms_arcmin", "candidate_rms_arcmin",
        "selected_rms_arcmin", "validation_improvement_fraction",
        "improved_fold_count", "fold_count", "refraction_a_arcsec",
        "refraction_b_arcsec", "refraction_status",
    ]
    keys = set().union(*(row.keys() for row in rows)) if rows else set(preferred)
    fields = [field for field in preferred if field in keys]
    fields.extend(sorted(keys - set(fields)))
    with products[0].open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)

    counts = Counter(str(row.get("status", "unknown")) for row in rows)
    families = Counter(str(row.get("family", "unknown")) for row in rows)
    summary = {
        "method": "nested zero/coupled Barghini models with radial soft-L1 fitting and deterministic angular-block validation",
        "ordinary_least_squares_used": False,
        "row_count": len(rows),
        "status_counts": dict(sorted(counts.items())),
        "family_counts": dict(sorted(families.items())),
        "rows": rows,
    }
    products[1].write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Integrated refraction replay",
        "",
        "All fits use radial soft-L1 robust least squares. The comparison uses fixed associations from saved full-fisheye solutions; location and timestamp metadata are not fit inputs.",
        "",
        f"Inputs: {len(rows)}. Statuses: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) + ".",
        "",
        "| Family | Hash | Status | Baseline RMS (arcmin) | Selected RMS (arcmin) | Validation gain | A (arcsec) | Failure/rejection |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        def shown(key: str, digits: int = 3) -> str:
            value = row.get(key)
            return "" if value in (None, "") else f"{float(value):.{digits}f}"
        lines.append(
            f"| {row.get('family', '')} | {str(row.get('source_sha256', ''))[:12]} | "
            f"{row.get('status', '')} | {shown('baseline_rms_arcmin')} | "
            f"{shown('selected_rms_arcmin')} | {shown('validation_improvement_fraction', 4)} | "
            f"{shown('refraction_a_arcsec', 2)} | {str(row.get('failure_reason', '')).replace('|', '/')} |"
        )
    products[2].write_text("\n".join(lines) + "\n")

    figure, axes = plt.subplots(1, 2, figsize=(11, 4.8), constrained_layout=True)
    successful = [row for row in rows if row.get("status") in {"adopted", "rejected_zero"}]
    if successful:
        labels = [f"{row['family']}\n{str(row.get('source_sha256', ''))[:6]}" for row in successful]
        x = np.arange(len(successful))
        baseline = [float(row["baseline_rms_arcmin"]) for row in successful]
        selected = [float(row["selected_rms_arcmin"]) for row in successful]
        gain = [100.0 * float(row["validation_improvement_fraction"]) for row in successful]
        axes[0].bar(x - .18, baseline, .36, label="zero refraction")
        axes[0].bar(x + .18, selected, .36, label="selected model")
        axes[0].set_xticks(x, labels, rotation=30, ha="right")
        axes[0].set_ylabel("Astrometric RMS (arcmin)")
        axes[0].legend()
        colours = ["tab:green" if row["status"] == "adopted" else "tab:gray"
                   for row in successful]
        axes[1].bar(x, gain, color=colours)
        physical_rejections = [
            index for index, row in enumerate(successful)
            if row.get("failure_reason") == "physical_checks_failed"
        ]
        if physical_rejections:
            axes[1].scatter(
                physical_rejections,
                np.zeros(len(physical_rejections)),
                marker="x",
                s=55,
                color="tab:red",
                label="rejected before validation folds",
                zorder=3,
            )
        axes[1].axhline(2.0, color="black", linestyle="--", linewidth=1,
                        label="2% adoption floor")
        axes[1].set_xticks(x, labels, rotation=30, ha="right")
        axes[1].set_ylabel("Blocked-validation robust cost gain (%)")
        axes[1].set_ylim(-0.12, 2.1)
        axes[1].legend()
    else:
        for axis in axes:
            axis.text(.5, .5, "No successful full-fisheye replay", ha="center", va="center")
            axis.set_axis_off()
    figure.suptitle("Integrated refraction inside the robust Barghini fit")
    figure.savefig(products[3], dpi=180)
    plt.close(figure)
    return products


def _argument(value: str) -> tuple[str | None, str]:
    if "=" in value:
        family, path = value.split("=", 1)
        return family, path
    return None, value


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument(
        "solutions", nargs="+",
        help="result.json, sqlite:DATABASE#RUN_ID, or FAMILY=REFERENCE",
    )
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--folds", type=int, default=4)
    command.add_argument("--max-nfev", type=int, default=600)
    return command


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    rows = []
    for supplied in arguments.solutions:
        family, path = _argument(supplied)
        print(f"Replaying {path}", flush=True)
        rows.append(analyse_solution(
            path, family, folds=arguments.folds, max_nfev=arguments.max_nfev))
    products = write_products(rows, arguments.output)
    print("Wrote " + ", ".join(str(path) for path in products), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
