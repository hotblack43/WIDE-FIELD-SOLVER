"""Historical saved-solution study for nested radial Barghini models."""
from __future__ import annotations

import csv
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Iterable, Sequence

import numpy as np
from astropy.time import Time

from point_star_barghini import (
    BarghiniCamera,
    angular_separations_arcmin,
    associate,
    vectors,
)
from point_star_epoch import Catalogue
from point_star_planet_ephemeris import MAJOR_PLANETS, MINOR_PLANETS, planet_vectors
from point_star_barghini import SOLVER_VERSION
from radial_model import ExtendedBarghiniCamera
from radial_statistics import (
    FitResult,
    cross_validate_orders,
    fit_extended_camera,
    select_supported_order,
)


SUCCESS_STATUSES = {
    "point_star_fit_converged",
    "joint_epoch_adopted",
    "joint_epoch_fit_converged",
}


@dataclass(frozen=True)
class SolutionRecord:
    path: Path
    source_sha256: str
    solver_version: str
    version_key: tuple[int, int, int]
    mtime_ns: int
    result: dict[str, object]


@dataclass
class SolutionData:
    record: SolutionRecord
    camera: BarghiniCamera
    xy: np.ndarray
    sky: np.ndarray
    coordinate_rows: list[dict[str, str]]
    coordinate_source: str
    epoch_jyear: float
    association_gate_arcmin: float | None
    source_group: str
    detections: list[dict[str, object]] | None = None
    association_catalogue: "AssociationCatalogue | None" = None


@dataclass(frozen=True)
class AssociationCatalogue:
    rows: list[dict[str, object]]
    sky: np.ndarray
    sha256: str
    epoch_jyear: float


@dataclass(frozen=True)
class StudyConfig:
    max_order: int = 5
    fold_count: int = 8
    bootstrap_replicates: int = 10_000
    seed: int = 0
    max_nfev: int = 600
    catalogue_paths_by_sha256: dict[str, Path] | None = None


@dataclass
class StudyResult:
    source_sha256: str
    source_group: str
    model_rows: list[dict[str, object]]
    fold_rows: list[dict[str, object]]
    selected_order: int
    robust_baseline: FitResult
    robust_selected: FitResult
    association_rows: list[dict[str, object]]
    planet_rows: list[dict[str, object]]
    operational_row: dict[str, object]
    association_failure_reason: str | None
    planet_failure_reason: str | None


def _semantic_version(value: object) -> tuple[int, int, int]:
    match = re.fullmatch(r"(?:v)?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?", str(value or ""))
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def _result_paths(paths: Sequence[str | Path]) -> list[Path]:
    found: set[Path] = set()
    for supplied in paths:
        path = Path(supplied).expanduser()
        if path.is_file() and path.name == "result.json":
            found.add(path.resolve())
        elif path.is_dir():
            found.update(candidate.resolve() for candidate in path.rglob("result.json"))
    return sorted(found)


def _read_fitted_rows(path: Path) -> tuple[list[dict[str, str]] | None, str | None]:
    coordinates = path.parent / "star_coordinates.csv"
    if not coordinates.is_file():
        return None, "missing_coordinates"
    try:
        with coordinates.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
    except (OSError, csv.Error, UnicodeError):
        return None, "malformed_coordinates"
    fitted = [row for row in rows if row.get("usage", "fitted") == "fitted"]
    if len(fitted) < 20:
        return None, "insufficient_fitted_associations"
    return fitted, None


def discover_solutions(
    paths: Sequence[str | Path],
) -> tuple[list[SolutionRecord], list[dict[str, object]]]:
    """Select the best successful result for each source hash and audit all files."""
    candidates: list[tuple[SolutionRecord, int]] = []
    inventory: list[dict[str, object]] = []
    for path in _result_paths(paths):
        row: dict[str, object] = {
            "path": str(path),
            "selected": False,
            "reason": None,
            "source_sha256": None,
            "solver_version": None,
        }
        inventory.append(row)
        try:
            result = json.loads(path.read_text())
            if not isinstance(result, dict):
                raise ValueError("result is not an object")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            row["reason"] = "malformed_json"
            continue
        source_hash = str(result.get("source_sha256", ""))
        version = str(result.get("solver_version", "0.0.0"))
        row.update(source_sha256=source_hash or None, solver_version=version)
        if result.get("status") not in SUCCESS_STATUSES:
            row["reason"] = "unsuccessful_status"
            continue
        if not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash):
            row["reason"] = "invalid_source_sha256"
            continue
        if not isinstance(result.get("camera"), dict):
            row["reason"] = "missing_camera"
            continue
        _, rejection = _read_fitted_rows(path)
        if rejection:
            row["reason"] = rejection
            continue
        record = SolutionRecord(
            path=path,
            source_sha256=source_hash.lower(),
            solver_version=version,
            version_key=_semantic_version(version),
            mtime_ns=path.stat().st_mtime_ns,
            result=result,
        )
        candidates.append((record, len(inventory) - 1))

    chosen_indices: set[int] = set()
    selected: list[SolutionRecord] = []
    by_source: dict[str, list[tuple[SolutionRecord, int]]] = {}
    for candidate in candidates:
        by_source.setdefault(candidate[0].source_sha256, []).append(candidate)
    for source_hash in sorted(by_source):
        choices = by_source[source_hash]
        chosen, inventory_index = max(
            choices,
            key=lambda item: (
                item[0].version_key,
                item[0].mtime_ns,
                str(item[0].path),
            ),
        )
        selected.append(chosen)
        chosen_indices.add(inventory_index)
        for _, index in choices:
            inventory[index]["reason"] = "selected" if index == inventory_index else "shadowed_duplicate"
            inventory[index]["selected"] = index == inventory_index
    selected.sort(key=lambda record: record.source_sha256)
    return selected, inventory


def _finite(row: dict[str, str], key: str) -> float | None:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _source_group(result: dict[str, object], camera: BarghiniCamera) -> str:
    source = Path(str(result.get("source", "unknown"))).as_posix().lower()
    family = re.sub(r"\d{4}[-_]?\d{2}[-_]?\d{2}", "<date>", source)
    family = re.sub(r"\d+", "#", family)
    family = re.sub(r"#+", "#", family)
    return f"{camera.shape[0]}x{camera.shape[1]}|{family}"


def load_solution(record: SolutionRecord) -> SolutionData:
    """Load fixed fitted associations from one selected historical solution."""
    rows, rejection = _read_fitted_rows(record.path)
    if rejection or rows is None:
        raise ValueError(rejection or "coordinates_unavailable")
    camera = BarghiniCamera.from_serialised(record.result["camera"])
    xy_values: list[tuple[float, float]] = []
    sky_values: list[tuple[float, float]] = []
    propagated = True
    for row in rows:
        x = _finite(row, "x_px")
        y = _finite(row, "y_px")
        ra = _finite(row, "propagated_ra_deg")
        dec = _finite(row, "propagated_dec_deg")
        if ra is None or dec is None:
            propagated = False
            ra = _finite(row, "catalog_ra_deg")
            dec = _finite(row, "catalog_dec_deg")
        if x is None or y is None or ra is None or dec is None:
            raise ValueError("non_finite_fixed_association")
        xy_values.append((x, y))
        sky_values.append((ra, dec))
    epoch_record = record.result.get("stellar_epoch", {})
    if not isinstance(epoch_record, dict):
        epoch_record = {}
    epoch = float(epoch_record.get("applied_epoch_jyear", 2000.0))
    association_record = record.result.get("association", {})
    if not isinstance(association_record, dict):
        association_record = {}
    gate_value = association_record.get("final_gate_arcmin")
    gate = float(gate_value) if gate_value is not None else None
    if not np.isfinite(epoch):
        raise ValueError("non_finite_stellar_epoch")
    if gate is not None and (not np.isfinite(gate) or gate <= 0.0):
        raise ValueError("invalid_association_gate")
    sky_coordinates = np.asarray(sky_values, dtype=float)
    return SolutionData(
        record=record,
        camera=camera,
        xy=np.asarray(xy_values, dtype=float),
        sky=vectors(sky_coordinates[:, 0], sky_coordinates[:, 1]),
        coordinate_rows=rows,
        coordinate_source="propagated" if propagated else "catalogue_fallback",
        epoch_jyear=epoch,
        association_gate_arcmin=gate,
        source_group=_source_group(record.result, camera),
    )


def catalogues_by_sha256(paths: Iterable[str | Path]) -> dict[str, Path]:
    """Index catalogue files solely by their byte checksum."""
    answer: dict[str, Path] = {}
    for supplied in paths:
        path = Path(supplied)
        candidates = [path] if path.is_file() else path.rglob("*.csv") if path.is_dir() else []
        for candidate in candidates:
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            answer.setdefault(digest, candidate.resolve())
    return answer


def load_association_catalogue(
    path: str | Path,
    *,
    expected_sha256: str,
    epoch_jyear: float,
) -> AssociationCatalogue:
    """Load and propagate the exact checksum-authoritative catalogue bytes."""
    source = Path(path)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest.lower() != expected_sha256.lower():
        raise ValueError("catalogue checksum does not match saved solution")
    with source.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    catalogue = Catalogue.from_rows(rows)
    return AssociationCatalogue(
        rows=[dict(row) for row in rows],
        sky=catalogue.at_year(epoch_jyear),
        sha256=digest,
        epoch_jyear=float(epoch_jyear),
    )


def _radial_bin(radius: float) -> str:
    edges = (0.0, 0.25, 0.50, 0.75, 1.0)
    for low, high in zip(edges[:-1], edges[1:], strict=True):
        if radius < high:
            return f"{low:.2f}-{high:.2f}"
    return ">=1.00"


def _association_map(
    camera: ExtendedBarghiniCamera,
    xy: np.ndarray,
    catalogue: AssociationCatalogue,
    gate_arcmin: float,
) -> dict[int, int]:
    detections, stars = associate(camera, xy, catalogue.sky, gate_arcmin)
    return {int(detection): int(star) for detection, star in zip(detections, stars, strict=True)}


def compare_associations(
    baseline: ExtendedBarghiniCamera,
    selected: ExtendedBarghiniCamera,
    detections: Sequence[dict[str, object]],
    catalogue: AssociationCatalogue,
    gate: float,
    *,
    expected_catalogue_sha256: str | None = None,
    saved_gate_arcmin: float | None = None,
) -> list[dict[str, object]]:
    """Compare catalogue matches while holding detections, catalogue, and gate fixed."""
    if expected_catalogue_sha256 is not None and (
        catalogue.sha256.lower() != expected_catalogue_sha256.lower()
    ):
        raise ValueError("catalogue checksum does not match saved solution")
    if saved_gate_arcmin is not None and float(gate) != float(saved_gate_arcmin):
        raise ValueError("comparison must use the saved association gate")
    if not np.isfinite(gate) or gate <= 0.0:
        raise ValueError("association gate must be positive and finite")
    xy = np.asarray(
        [[float(row["x_px"]), float(row["y_px"])] for row in detections],
        dtype=float,
    )
    baseline_matches = _association_map(baseline, xy, catalogue, gate)
    selected_matches = _association_map(selected, xy, catalogue, gate)
    centre = np.array([baseline.physical.x_o, baseline.physical.y_o])
    radii = np.linalg.norm(xy - centre, axis=1) / baseline.scale

    def star_id(index: int | None) -> str | None:
        return None if index is None else str(catalogue.rows[index].get("star_id", index))

    def residuals(
        camera: ExtendedBarghiniCamera, detection_index: int, star_index: int | None
    ) -> tuple[float | None, float | None]:
        if star_index is None:
            return None, None
        measured_sky = camera.to_sky(xy[detection_index : detection_index + 1])
        angular = float(
            angular_separations_arcmin(
                measured_sky, catalogue.sky[star_index : star_index + 1]
            )[0]
        )
        predicted = camera.project(catalogue.sky[star_index : star_index + 1])[0]
        pixel = float(np.linalg.norm(predicted - xy[detection_index]))
        return angular, pixel

    rows: list[dict[str, object]] = []
    for index, detection in enumerate(detections):
        old = baseline_matches.get(index)
        new = selected_matches.get(index)
        if old is None and new is None:
            outcome = "unmatched"
        elif old is None:
            outcome = "gained"
        elif new is None:
            outcome = "lost"
        elif old == new:
            outcome = "common"
        else:
            outcome = "changed"
        baseline_angular, baseline_pixel = residuals(baseline, index, old)
        selected_angular, selected_pixel = residuals(selected, index, new)
        rows.append(
            {
                "detection_id": str(detection["detection_id"]),
                "outcome": outcome,
                "baseline_star_id": star_id(old),
                "selected_star_id": star_id(new),
                "baseline_residual_arcmin": baseline_angular,
                "selected_residual_arcmin": selected_angular,
                "baseline_residual_px": baseline_pixel,
                "selected_residual_px": selected_pixel,
                "normalised_radius": float(radii[index]),
                "radial_bin": _radial_bin(float(radii[index])),
                "gate_arcmin": float(gate),
                "detection_count": len(detections),
                "catalogue_sha256": catalogue.sha256,
                "catalogue_epoch_jyear": catalogue.epoch_jyear,
            }
        )
    return rows


def _read_detection_rows(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        raise FileNotFoundError(f"missing detection table: {path}")
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    answer: list[dict[str, object]] = []
    for row in rows:
        try:
            answer.append(
                {
                    **row,
                    "detection_id": str(row["detection_id"]),
                    "x_px": float(row["x_px"]),
                    "y_px": float(row["y_px"]),
                }
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("malformed detection table") from error
    return answer


def _association_inputs(
    solution: SolutionData, config: StudyConfig
) -> tuple[list[dict[str, object]], AssociationCatalogue] | None:
    if solution.detections is not None and solution.association_catalogue is not None:
        return solution.detections, solution.association_catalogue
    detection_path = solution.record.path.parent / "dots/star_candidates.csv"
    expected = str(solution.record.result.get("catalogue_sha256", "")).lower()
    catalogue_index = config.catalogue_paths_by_sha256 or {}
    catalogue_path = catalogue_index.get(expected)
    if not detection_path.is_file() or catalogue_path is None:
        return None
    return (
        _read_detection_rows(detection_path),
        load_association_catalogue(
            catalogue_path,
            expected_sha256=expected,
            epoch_jyear=solution.epoch_jyear,
        ),
    )


def compare_solution(solution: SolutionData, config: StudyConfig) -> StudyResult:
    """Run statistical selection, operational refits, and edge-yield comparison."""
    if config.max_order < 0 or config.max_order > 5:
        raise ValueError("max_order must lie between zero and five")
    initial = ExtendedBarghiniCamera.from_camera(solution.camera, [])
    model_rows, fold_rows = cross_validate_orders(
        initial,
        solution.xy,
        solution.sky,
        orders=list(range(config.max_order + 1)),
        fold_count=config.fold_count,
        bootstrap_replicates=config.bootstrap_replicates,
        seed=config.seed,
        max_nfev=config.max_nfev,
    )
    supported = select_supported_order(model_rows)
    selected_order = 0 if supported is None else supported
    robust_baseline = fit_extended_camera(
        initial,
        solution.xy,
        solution.sky,
        robust=True,
        max_nfev=config.max_nfev,
    )
    selected_start = ExtendedBarghiniCamera(
        solution.camera.shape,
        solution.camera.reference_rotation,
        robust_baseline.camera.p.copy(),
        np.zeros(selected_order),
        solution.camera.detector_parity,
    )
    robust_selected = (
        robust_baseline
        if selected_order == 0
        else fit_extended_camera(
            selected_start,
            solution.xy,
            solution.sky,
            robust=True,
            max_nfev=config.max_nfev,
        )
    )
    association_rows: list[dict[str, object]] = []
    association_failure_reason = None
    inputs = _association_inputs(solution, config)
    if solution.association_gate_arcmin is None:
        association_failure_reason = "saved_association_gate_unavailable"
    elif inputs is not None and robust_baseline.success and robust_selected.success:
        detections, catalogue = inputs
        association_rows = compare_associations(
            robust_baseline.camera,
            robust_selected.camera,
            detections,
            catalogue,
            solution.association_gate_arcmin,
            expected_catalogue_sha256=str(
                solution.record.result.get("catalogue_sha256", "")
            ),
            saved_gate_arcmin=solution.association_gate_arcmin,
        )
    elif inputs is None:
        association_failure_reason = "association_inputs_unavailable"
    else:
        association_failure_reason = "operational_fit_failed"
    planet_rows: list[dict[str, object]] = []
    planet_failure_reason = None
    planet_path = solution.record.path.parent / "planet_candidates.csv"
    if planet_path.is_file() and robust_baseline.success and robust_selected.success:
        with planet_path.open(newline="") as stream:
            candidates = list(csv.DictReader(stream))
        planet_gate = _load_planet_gate(solution.record.path)
        if planet_gate is None:
            planet_failure_reason = "saved_planet_gate_unavailable"
        planet_rows = compare_planet_residuals(
            robust_baseline.camera,
            robust_selected.camera,
            candidates,
            planet_gate,
        )
    elif planet_path.is_file():
        planet_failure_reason = "operational_fit_failed"
    else:
        planet_failure_reason = "planet_candidates_unavailable"
    operational_row = _operational_comparison(
        solution, selected_order, robust_baseline, robust_selected
    )
    return StudyResult(
        source_sha256=solution.record.source_sha256,
        source_group=solution.source_group,
        model_rows=model_rows,
        fold_rows=fold_rows,
        selected_order=selected_order,
        robust_baseline=robust_baseline,
        robust_selected=robust_selected,
        association_rows=association_rows,
        planet_rows=planet_rows,
        operational_row=operational_row,
        association_failure_reason=association_failure_reason,
        planet_failure_reason=planet_failure_reason,
    )


def _load_planet_gate(result_path: Path) -> float | None:
    """Read the gate recorded by the historical planet-search sidecar."""
    candidates = (
        result_path.parent / "planet_epoch.json",
        result_path.parent / "science_summary.json",
    )
    for path in candidates:
        if not path.is_file():
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        values = [record.get("gate_arcmin")]
        planets = record.get("planets", {})
        if isinstance(planets, dict):
            values.append(planets.get("gate_arcmin"))
        for value in values:
            if value is None:
                continue
            gate = float(value)
            if not np.isfinite(gate) or gate <= 0.0:
                raise ValueError("invalid_planet_gate")
            return gate
    return None


def _fit_record(prefix: str, result: FitResult) -> dict[str, object]:
    return {
        f"{prefix}_success": result.success,
        f"{prefix}_failure_reason": result.failure_reason,
        f"{prefix}_rms_arcmin": result.rms_arcmin,
        f"{prefix}_rms_px": result.rms_px,
        f"{prefix}_rss_arcmin2": result.rss_arcmin2,
        f"{prefix}_nfev": result.nfev,
        f"{prefix}_camera": result.camera.serialise(),
        f"{prefix}_radial_coefficients": result.camera.coefficients.tolist(),
    }


def _operational_comparison(
    solution: SolutionData,
    selected_order: int,
    baseline: FitResult,
    selected: FitResult,
) -> dict[str, object]:
    saved_fit = solution.record.result.get("fit", {})
    if not isinstance(saved_fit, dict):
        saved_fit = {}
    saved_rms_px = saved_fit.get("rms_px")
    saved_rms_arcmin = saved_fit.get("rms_arcmin")
    return {
        "selected_order": selected_order,
        "saved_fit_count": saved_fit.get("count"),
        "saved_rms_px": saved_rms_px,
        "saved_rms_arcmin": saved_rms_arcmin,
        "association_gate_arcmin": solution.association_gate_arcmin,
        **_fit_record("robust_baseline", baseline),
        **_fit_record("robust_selected", selected),
        "selected_minus_baseline_rms_px": selected.rms_px - baseline.rms_px,
        "selected_minus_baseline_rms_arcmin": selected.rms_arcmin - baseline.rms_arcmin,
        "selected_minus_saved_rms_px": (
            selected.rms_px - float(saved_rms_px)
            if isinstance(saved_rms_px, (int, float)) else None
        ),
        "association_failure_reason": None,
        "planet_failure_reason": None,
    }


def _candidate_epoch_jd(value: object) -> float:
    text = str(value).strip()
    if not text:
        raise ValueError("planet candidate is missing its fixed epoch")
    parse_text = re.sub(r"\s+TDB\s*$", "", text, flags=re.IGNORECASE)
    try:
        numeric = float(parse_text)
    except ValueError:
        date = Time(parse_text, scale="tdb")
    else:
        date = Time(numeric, format="jd", scale="tdb")
    jd = float(date.tdb.jd)
    if not np.isfinite(jd):
        raise ValueError("planet candidate epoch is non-finite")
    return jd


def compare_planet_residuals(
    baseline: ExtendedBarghiniCamera,
    selected: ExtendedBarghiniCamera,
    candidates: Sequence[dict[str, object]],
    gate: float | None,
) -> list[dict[str, object]]:
    """Compare cameras for fixed planet identities, detections, and candidate dates."""
    if gate is not None and (not np.isfinite(gate) or gate <= 0.0):
        raise ValueError("planet gate must be positive and finite")
    centre = np.array([baseline.physical.x_o, baseline.physical.y_o])
    rows: list[dict[str, object]] = []
    supported = set(MAJOR_PLANETS) | set(MINOR_PLANETS)
    for candidate in candidates:
        display_name = str(candidate.get("planet") or candidate.get("identity_name") or "").strip()
        name = display_name.lower()
        if name not in supported:
            raise ValueError(f"unsupported fixed planet identity: {display_name!r}")
        epoch_text = str(candidate.get("epoch_tdb", "")).strip()
        jd = _candidate_epoch_jd(epoch_text)
        x_value = candidate.get("measured_x_px", candidate.get("x_px"))
        y_value = candidate.get("measured_y_px", candidate.get("y_px"))
        xy = np.array([[float(x_value), float(y_value)]], dtype=float)
        if not np.all(np.isfinite(xy)):
            raise ValueError("planet candidate has non-finite measured pixels")
        body = planet_vectors(name, jd)
        baseline_pixel = float(np.linalg.norm(baseline.project(body)[0] - xy[0]))
        selected_pixel = float(np.linalg.norm(selected.project(body)[0] - xy[0]))
        baseline_angular = float(
            angular_separations_arcmin(baseline.to_sky(xy), body)[0]
        )
        selected_angular = float(
            angular_separations_arcmin(selected.to_sky(xy), body)[0]
        )
        difference = selected_angular - baseline_angular
        if difference < -1.0e-12:
            classification = "improved"
        elif difference > 1.0e-12:
            classification = "worsened"
        else:
            classification = "unchanged"
        old_inside = baseline_angular < gate if gate is not None else None
        new_inside = selected_angular < gate if gate is not None else None
        if gate is None:
            crossing = "gate_unavailable"
        elif not old_inside and new_inside:
            crossing = "outside_to_inside"
        elif old_inside and not new_inside:
            crossing = "inside_to_outside"
        elif old_inside:
            crossing = "stayed_inside"
        else:
            crossing = "stayed_outside"
        radius = float(np.linalg.norm(xy[0] - centre) / baseline.scale)
        rows.append(
            {
                "detection_id": str(candidate["detection_id"]),
                "planet": display_name,
                "identity_type": "minor_planet" if name in MINOR_PLANETS else "major_planet",
                "epoch_tdb": epoch_text,
                "epoch_jd_tdb": jd,
                "measured_x_px": float(xy[0, 0]),
                "measured_y_px": float(xy[0, 1]),
                "normalised_radius": radius,
                "radial_bin": _radial_bin(radius),
                "gate_arcmin": float(gate) if gate is not None else None,
                "baseline_separation_arcmin": baseline_angular,
                "selected_separation_arcmin": selected_angular,
                "baseline_separation_px": baseline_pixel,
                "selected_separation_px": selected_pixel,
                "classification": classification,
                "gate_crossing": crossing,
                "baseline_inside_gate": old_inside,
                "selected_inside_gate": new_inside,
            }
        )
    return rows


def _analyse_record(record: SolutionRecord, config: StudyConfig) -> StudyResult:
    return compare_solution(load_solution(record), config)


def _json_safe(value: object) -> object:
    """Convert study values to strict JSON without preserving NaN or infinity."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _study_payload(result: StudyResult) -> dict[str, object]:
    operational = {
        **result.operational_row,
        "association_failure_reason": result.association_failure_reason,
        "planet_failure_reason": result.planet_failure_reason,
    }
    return _json_safe(
        {
            "source_sha256": result.source_sha256,
            "source_group": result.source_group,
            "model_rows": result.model_rows,
            "fold_rows": result.fold_rows,
            "selected_order": result.selected_order,
            "association_rows": result.association_rows,
            "planet_rows": result.planet_rows,
            "operational_row": operational,
            "association_failure_reason": result.association_failure_reason,
            "planet_failure_reason": result.planet_failure_reason,
        }
    )


def _write_checkpoint(
    path: Path,
    signature: str,
    *,
    payload: dict[str, object] | None,
    failure: str | None,
) -> None:
    """Atomically retain one completed image without exposing partial final output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    record = _json_safe(
        {
            "schema": 1,
            "signature": signature,
            "payload": payload,
            "failure": failure,
        }
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(record, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_checkpoint(path: Path, signature: str) -> dict[str, object] | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(record, dict)
        or record.get("schema") != 1
        or record.get("signature") != signature
        or (record.get("payload") is None) == (record.get("failure") is None)
    ):
        return None
    return record


def _checkpoint_signature(
    selected: Sequence[SolutionRecord],
    config: StudyConfig,
    catalogue_index: dict[str, Path],
) -> str:
    digest = hashlib.sha256()
    for source in (Path(__file__), Path(__file__).with_name("radial_model.py"),
                   Path(__file__).with_name("radial_statistics.py")):
        digest.update(source.name.encode("utf-8"))
        digest.update(source.read_bytes())
    parameters = {
        "max_order": config.max_order,
        "fold_count": config.fold_count,
        "bootstrap_replicates": config.bootstrap_replicates,
        "seed": config.seed,
        "max_nfev": config.max_nfev,
        "catalogue_sha256": sorted(catalogue_index),
        "solutions": [
            {
                "source_sha256": record.source_sha256,
                "path": str(record.path),
                "mtime_ns": record.mtime_ns,
                "size": record.path.stat().st_size,
            }
            for record in selected
        ],
    }
    digest.update(json.dumps(parameters, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    return value


def _write_rows(
    path: Path,
    rows: Sequence[dict[str, object]],
    required_fields: Sequence[str],
) -> None:
    fields = list(required_fields)
    fields.extend(
        sorted({key for row in rows for key in row} - set(required_fields))
    )
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fields})


def _cluster_bootstrap_interval(
    model_rows: Sequence[dict[str, object]], seed: int, replicates: int
) -> list[float] | None:
    grouped: dict[str, list[float]] = {}
    for row in model_rows:
        value = row.get("validation_delta_rms_arcmin")
        if int(row.get("order", 0)) == 0 or not isinstance(value, (int, float)):
            continue
        if np.isfinite(value):
            grouped.setdefault(str(row["source_group"]), []).append(float(value))
    if not grouped:
        return None
    groups = sorted(grouped)
    rng = np.random.default_rng(seed)
    samples = []
    for _ in range(replicates):
        selected_groups = rng.choice(groups, size=len(groups), replace=True)
        values = [value for group in selected_groups for value in grouped[group]]
        samples.append(float(np.median(values)))
    return [float(value) for value in np.quantile(samples, [0.025, 0.975])]


def aggregate_study(
    model_rows: Sequence[dict[str, object]],
    association_rows: Sequence[dict[str, object]],
    *,
    seed: int,
    bootstrap_replicates: int,
) -> dict[str, object]:
    by_order: dict[str, dict[str, object]] = {}
    for order in sorted({int(row["order"]) for row in model_rows}):
        rows = [row for row in model_rows if int(row["order"]) == order]
        fitted = [
            float(row["rms_arcmin"]) for row in rows
            if isinstance(row.get("rms_arcmin"), (int, float))
            and np.isfinite(row["rms_arcmin"])
        ]
        validation_change = [
            float(row["validation_delta_rms_arcmin"]) for row in rows
            if isinstance(row.get("validation_delta_rms_arcmin"), (int, float))
            and np.isfinite(row["validation_delta_rms_arcmin"])
        ]
        by_order[str(order)] = {
            "image_count": len(rows),
            "classification_counts": dict(sorted(Counter(str(row.get("classification")) for row in rows).items())),
            "failure_count": sum(not bool(row.get("fit_valid")) for row in rows),
            "fitted_rms_arcmin_quartiles": (
                [float(value) for value in np.quantile(fitted, [0.25, 0.5, 0.75])]
                if fitted else None
            ),
            "validation_delta_rms_arcmin_quartiles": (
                [float(value) for value in np.quantile(validation_change, [0.25, 0.5, 0.75])]
                if validation_change else None
            ),
        }
    return {
        "image_count": len({str(row["source_sha256"]) for row in model_rows}),
        "source_group_count": len({str(row["source_group"]) for row in model_rows}),
        "by_order": by_order,
        "association_outcomes": dict(sorted(Counter(str(row["outcome"]) for row in association_rows).items())),
        "cluster_bootstrap_validation_delta_median_95_interval_arcmin": _cluster_bootstrap_interval(
            model_rows, seed, bootstrap_replicates
        ),
    }


def _plot_study(
    output: Path,
    model_rows: Sequence[dict[str, object]],
    association_rows: Sequence[dict[str, object]],
) -> None:
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    figure, axis = plt.subplots(figsize=(7, 4.5))
    plotted = False
    for outcome in ("common", "gained", "lost", "changed"):
        rows = [row for row in association_rows if row.get("outcome") == outcome]
        values = [
            (
                float(row["normalised_radius"]),
                float(row["selected_residual_arcmin"]) - float(row["baseline_residual_arcmin"]),
            )
            for row in rows
            if row.get("selected_residual_arcmin") is not None
            and row.get("baseline_residual_arcmin") is not None
        ]
        if values:
            axis.scatter(*np.asarray(values).T, s=12, alpha=0.65, label=outcome)
            plotted = True
    axis.axhline(0.0, color="0.4", linewidth=0.8)
    axis.set(xlabel="Normalized detector radius", ylabel="Selected − baseline residual (arcmin)")
    if plotted:
        axis.legend()
    else:
        axis.text(0.5, 0.5, "No paired association residuals", ha="center", transform=axis.transAxes)
    figure.tight_layout()
    figure.savefig(output / "radial_profiles.png", dpi=140)
    plt.close(figure)

    extensions = [row for row in model_rows if int(row.get("order", 0)) > 0]
    figure, axis = plt.subplots(figsize=(6, 5))
    pairs = [
        (float(row["rms_arcmin"]), float(row["validation_delta_rms_arcmin"]))
        for row in extensions
        if isinstance(row.get("rms_arcmin"), (int, float))
        and isinstance(row.get("validation_delta_rms_arcmin"), (int, float))
    ]
    if pairs:
        values = np.asarray(pairs)
        axis.scatter(values[:, 0], values[:, 1], s=18, alpha=0.7)
    else:
        axis.text(0.5, 0.5, "No valid extension fits", ha="center", transform=axis.transAxes)
    axis.axhline(0.0, color="0.4", linewidth=0.8)
    axis.set(xlabel="Fitted angular RMS (arcmin)", ylabel="Validation RMS change (arcmin)")
    figure.tight_layout()
    figure.savefig(output / "fit_vs_validation.png", dpi=140)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(7, 4.5))
    for key, marker in (("delta_aicc", "o"), ("delta_bic", "x")):
        pairs = [
            (int(row["order"]), float(row[key]))
            for row in extensions
            if isinstance(row.get(key), (int, float)) and np.isfinite(row[key])
        ]
        if pairs:
            values = np.asarray(pairs)
            axis.scatter(values[:, 0], values[:, 1], marker=marker, alpha=0.65, label=key)
    axis.axhline(0.0, color="0.4", linewidth=0.8)
    axis.axhline(-10.0, color="0.6", linewidth=0.8, linestyle="--")
    axis.set(xlabel="Added radial terms", ylabel="Criterion change from M0")
    if axis.collections:
        axis.legend()
    figure.tight_layout()
    figure.savefig(output / "information_criteria.png", dpi=140)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(7, 4.5))
    orders = sorted({int(row["order"]) for row in model_rows})
    failures = [sum(not bool(row.get("fit_valid")) for row in model_rows if int(row["order"]) == order) for order in orders]
    axis.bar(orders, failures)
    axis.set(xlabel="Added radial terms", ylabel="Failed image fits", xticks=orders)
    figure.tight_layout()
    figure.savefig(output / "failure_counts.png", dpi=140)
    plt.close(figure)


def _write_summary(path: Path, aggregate: dict[str, object], planet_rows: Sequence[dict[str, object]]) -> None:
    outcomes = aggregate["association_outcomes"]
    lines = [
        "# Nested radial-model study",
        "",
        f"Analyzed images: {aggregate['image_count']} in {aggregate['source_group_count']} source groups.",
        "",
        "The association comparison asks whether the selected camera can associate more already-detected sources. "
        "These are not newly detected image objects; source detection is unchanged.",
        "",
        "Association outcomes: " + ", ".join(f"{key}={value}" for key, value in outcomes.items()) + ".",
        f"Fixed-identity planet candidate rows retained: {len(planet_rows)}.",
        "",
        "AICc and BIC use the ordinary Gaussian tangent-coordinate fit. The robust soft-L1 fits are an operational sensitivity check after selection. Spatial validation and all failures remain in the CSV and JSON evidence.",
        "",
        "No extension becomes the ordinary blind-solver default from this experiment alone.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_batch(
    solution_paths: Sequence[str | Path],
    catalogue_paths: Sequence[str | Path],
    output: str | Path,
    *,
    workers: int = 1,
    max_order: int = 5,
    fold_count: int = 8,
    bootstrap_replicates: int = 10_000,
    seed: int = 0,
    max_nfev: int = 600,
) -> int:
    """Analyze every usable unique saved source and publish an atomic evidence set."""
    destination = Path(output).expanduser().resolve()
    supplied = [Path(path).expanduser().resolve() for path in solution_paths]
    if destination.exists():
        raise FileExistsError(f"output already exists: {destination}")
    if destination in supplied:
        raise ValueError("output cannot overwrite an input")
    package = Path(__file__).resolve().parent
    if destination == package or package in destination.parents:
        raise ValueError("output cannot overwrite the preserved runtime package")
    if workers < 1:
        raise ValueError("workers must be positive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    selected, inventory = discover_solutions(supplied)
    catalogue_index = catalogues_by_sha256(catalogue_paths)
    config = StudyConfig(
        max_order=max_order,
        fold_count=fold_count,
        bootstrap_replicates=bootstrap_replicates,
        seed=seed,
        max_nfev=max_nfev,
        catalogue_paths_by_sha256=catalogue_index,
    )
    signature = _checkpoint_signature(selected, config, catalogue_index)
    checkpoint_directory = destination.parent / f".{destination.name}-checkpoints"
    results: list[dict[str, object]] = []
    failures: dict[str, str] = {}
    pending: list[SolutionRecord] = []
    for record in selected:
        checkpoint = _load_checkpoint(
            checkpoint_directory / f"{record.source_sha256}.json", signature
        )
        if checkpoint is None:
            pending.append(record)
        elif checkpoint["payload"] is not None:
            results.append(checkpoint["payload"])
        else:
            failures[record.source_sha256] = str(checkpoint["failure"])
    completed = len(selected) - len(pending)
    if completed:
        print(f"Resuming with {completed}/{len(selected)} unique images checkpointed", flush=True)

    def retain(record: SolutionRecord, result: StudyResult | None, failure: str | None) -> None:
        payload = _study_payload(result) if result is not None else None
        _write_checkpoint(
            checkpoint_directory / f"{record.source_sha256}.json",
            signature,
            payload=payload,
            failure=failure,
        )
        if payload is not None:
            results.append(payload)
        else:
            failures[record.source_sha256] = str(failure)

    if workers == 1:
        for record in pending:
            try:
                retain(record, _analyse_record(record, config), None)
            except Exception as error:  # Per-image failure is required evidence.
                retain(record, None, f"{type(error).__name__}: {error}")
            completed += 1
            print(f"Analyzed {completed}/{len(selected)} unique images", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            future_records = {
                pool.submit(_analyse_record, record, config): record for record in pending
            }
            for future in as_completed(future_records):
                record = future_records[future]
                try:
                    retain(record, future.result(), None)
                except Exception as error:
                    retain(record, None, f"{type(error).__name__}: {error}")
                completed += 1
                print(f"Analyzed {completed}/{len(selected)} unique images", flush=True)
    results.sort(key=lambda result: str(result["source_sha256"]))
    for row in inventory:
        source_hash = row.get("source_sha256")
        if source_hash in failures:
            row["analysis_failure"] = failures[source_hash]

    model_rows: list[dict[str, object]] = []
    fold_rows: list[dict[str, object]] = []
    association_rows: list[dict[str, object]] = []
    planet_rows: list[dict[str, object]] = []
    operational_rows: list[dict[str, object]] = []
    for result in results:
        prefix = {"source_sha256": result["source_sha256"], "source_group": result["source_group"]}
        model_rows.extend({**prefix, **row, "selected_order": result["selected_order"]} for row in result["model_rows"])
        fold_rows.extend({**prefix, **row} for row in result["fold_rows"])
        association_rows.extend({**prefix, **row, "selected_order": result["selected_order"]} for row in result["association_rows"])
        planet_rows.extend({**prefix, **row, "selected_order": result["selected_order"]} for row in result["planet_rows"])
        operational_rows.append({**prefix, **result["operational_row"]})
    for record in selected:
        if record.source_sha256 not in failures:
            continue
        camera_record = record.result.get("camera", {})
        shape = camera_record.get("shape", [None, None]) if isinstance(camera_record, dict) else [None, None]
        group = f"{shape[0]}x{shape[1]}|analysis-failed"
        for order in range(max_order + 1):
            model_rows.append(
                {
                    "source_sha256": record.source_sha256,
                    "source_group": group,
                    "order": order,
                    "fit_valid": False,
                    "failure_reason": failures[record.source_sha256],
                    "classification": "failed",
                    "selected_order": 0,
                }
            )
    model_rows.sort(key=lambda row: (str(row["source_sha256"]), int(row["order"])))
    fold_rows.sort(key=lambda row: (str(row["source_sha256"]), int(row["order"]), int(row["fold"])))
    association_rows.sort(key=lambda row: (str(row["source_sha256"]), str(row["detection_id"])))
    planet_rows.sort(key=lambda row: (str(row["source_sha256"]), str(row["detection_id"]), str(row["planet"])))
    operational_rows.sort(key=lambda row: str(row["source_sha256"]))
    inventory.sort(key=lambda row: str(row["path"]))
    aggregate = aggregate_study(
        model_rows,
        association_rows,
        seed=seed,
        bootstrap_replicates=bootstrap_replicates,
    )

    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        _write_rows(temporary / "solution_inventory.csv", inventory, ("path", "source_sha256", "solver_version", "selected", "reason", "analysis_failure"))
        _write_rows(temporary / "model_comparison.csv", model_rows, ("source_sha256", "source_group", "order", "selected_order", "fit_valid", "failure_reason", "aicc", "bic", "classification"))
        _write_rows(temporary / "validation_folds.csv", fold_rows, ("source_sha256", "source_group", "order", "fold", "fit_valid", "failure_reason", "training_count", "holdout_count", "holdout_rms_arcmin"))
        _write_rows(temporary / "association_yield.csv", association_rows, ("source_sha256", "source_group", "selected_order", "detection_id", "outcome", "normalised_radius", "radial_bin"))
        _write_rows(temporary / "planet_residual_comparison.csv", planet_rows, ("source_sha256", "source_group", "selected_order", "detection_id", "planet", "identity_type", "epoch_tdb", "classification", "gate_crossing"))
        _write_rows(temporary / "operational_comparison.csv", operational_rows, ("source_sha256", "source_group", "selected_order", "saved_fit_count", "saved_rms_px", "saved_rms_arcmin", "robust_baseline_success", "robust_baseline_rms_px", "robust_baseline_rms_arcmin", "robust_selected_success", "robust_selected_rms_px", "robust_selected_rms_arcmin", "selected_minus_baseline_rms_px", "selected_minus_baseline_rms_arcmin", "selected_minus_saved_rms_px", "association_gate_arcmin", "association_failure_reason", "planet_failure_reason"))
        payload = {
            "configuration": {
                "solution_paths": [str(path) for path in supplied],
                "catalogue_paths": [str(Path(path).expanduser().resolve()) for path in catalogue_paths],
                "workers": workers,
                "max_order": max_order,
                "fold_count": fold_count,
                "bootstrap_replicates": bootstrap_replicates,
                "seed": seed,
                "max_nfev": max_nfev,
            },
            "provenance": {
                "solver_version": SOLVER_VERSION,
                "method": "fixed-association Gaussian AICc/BIC plus spatial validation and robust operational refits",
                "information_parameter_count": "camera parameters plus fitted Gaussian variance",
                "validation": "contiguous radial/azimuth holdout blocks",
            },
            "aggregate": aggregate,
            "solution_inventory": inventory,
            "model_comparison": model_rows,
            "validation_folds": fold_rows,
            "association_yield": association_rows,
            "planet_residual_comparison": planet_rows,
            "operational_comparison": operational_rows,
        }
        (temporary / "radial_model_study.json").write_text(
            json.dumps(_json_safe(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        _write_summary(temporary / "summary.md", aggregate, planet_rows)
        _plot_study(temporary, model_rows, association_rows)
        temporary.replace(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return 0 if results else 2
