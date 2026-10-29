"""Machine-readable products and faithful diagnostic figures."""

from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .dynamics import SOLAR_GM_AU3_DAY2, propagate_two_body, state_to_elements
from .geometry import predict_topocentric_unit, tangent_residuals_arcmin
from .types import Observation, OrbitFitResult


def _atomic_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _atomic_figure(path: Path, figure: plt.Figure) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    figure.savefig(temporary, format="png", dpi=150, bbox_inches="tight")
    plt.close(figure)
    temporary.replace(path)


def _radec(unit: Sequence[float]) -> tuple[float, float]:
    vector = np.asarray(unit, dtype=float)
    ra = math.degrees(math.atan2(float(vector[1]), float(vector[0]))) % 360.0
    dec = math.degrees(math.asin(float(np.clip(vector[2], -1.0, 1.0))))
    return ra, dec


def _observations(extraction) -> tuple[Observation, ...]:
    if isinstance(extraction, Mapping):
        rows = extraction.get("observations", ())
    else:
        rows = extraction.observations
    return tuple(rows)


def _write_observation_products(output: Path, observations: tuple[Observation, ...], evaluation) -> list[Path]:
    withheld_ids = {row.direction.run_id for row in evaluation.split.withheld}
    fit_rows = {}
    if evaluation.primary_fit.solutions:
        fit_rows = {row.run_id: row for row in evaluation.primary_fit.solutions[0].observation_fits}
    observation_rows = []
    audit_rows = []
    for row in observations:
        ra, dec = _radec(row.measured_unit)
        observation_rows.append({
            "object_id": row.direction.object_id,
            "run_id": row.direction.run_id,
            "source_sha256": row.direction.source_sha256,
            "night": row.direction.night,
            "jd_tdb": f"{row.jd_tdb:.12f}",
            "unit_x": repr(float(row.measured_unit[0])),
            "unit_y": repr(float(row.measured_unit[1])),
            "unit_z": repr(float(row.measured_unit[2])),
            "ra_icrs_deg": f"{ra:.12f}",
            "dec_icrs_deg": f"{dec:.12f}",
            "sigma_arcmin": repr(float(row.sigma_arcmin)),
            "partition": "withheld" if row.direction.run_id in withheld_ids else "fit",
        })
        fitted = fit_rows.get(row.direction.run_id)
        audit_rows.append({
            "run_id": row.direction.run_id,
            "source_path": row.direction.source_path,
            "detection_id": row.direction.detection_id,
            "x_px": repr(float(row.direction.x_px)),
            "y_px": repr(float(row.direction.y_px)),
            "source_class": row.direction.source_class,
            "saturated": str(row.direction.saturated),
            "integrated_refraction_status": row.direction.integrated_refraction_status,
            "fit_status": fitted.status if fitted else "not_in_primary_fit",
            "fit_reason": fitted.reason if fitted else "withheld_or_unresolved",
            "robust_weight": repr(float(fitted.robust_weight)) if fitted else "",
        })
    observations_path = output / "observations.csv"
    audit_path = output / "observation_audit.csv"
    _atomic_csv(observations_path, list(observation_rows[0]), observation_rows)
    _atomic_csv(audit_path, list(audit_rows[0]), audit_rows)
    manifest = output / "fit_input_manifest.json"
    _atomic_json(manifest, {
        "schema": "anonymous_direction_v1",
        "object_id": "Object A",
        "row_count": len(observations),
        "fields": ["object_id", "run_id", "source_sha256", "night", "jd_tdb",
                   "unit_x", "unit_y", "unit_z", "sigma_arcmin"],
        "run_ids": [row.direction.run_id for row in observations],
    })
    return [observations_path, audit_path, manifest]


def _write_fit_tables(output: Path, fit: OrbitFitResult, evaluation) -> list[Path]:
    candidate_rows = []
    element_rows = []
    for family_index, solution in enumerate(fit.solutions):
        candidate_rows.append({
            "family": family_index, "seed_index": solution.seed_index,
            "reference_jd_tdb": repr(solution.state.reference_jd_tdb),
            "x_au": repr(solution.state.position_au[0]), "y_au": repr(solution.state.position_au[1]),
            "z_au": repr(solution.state.position_au[2]),
            "vx_au_per_day": repr(solution.state.velocity_au_per_day[0]),
            "vy_au_per_day": repr(solution.state.velocity_au_per_day[1]),
            "vz_au_per_day": repr(solution.state.velocity_au_per_day[2]),
            "cost": repr(solution.cost), "success": str(solution.success),
        })
        elements = solution.elements
        element_rows.append({
            "family": family_index, "reference_jd_tdb": repr(elements.reference_jd_tdb),
            "semimajor_axis_au": repr(elements.semimajor_axis_au),
            "eccentricity": repr(elements.eccentricity), "inclination_deg": repr(elements.inclination_deg),
            "longitude_ascending_node_deg": "" if elements.longitude_ascending_node_deg is None else repr(elements.longitude_ascending_node_deg),
            "argument_perihelion_deg": "" if elements.argument_perihelion_deg is None else repr(elements.argument_perihelion_deg),
            "mean_anomaly_deg": "" if elements.mean_anomaly_deg is None else repr(elements.mean_anomaly_deg),
            "singular_flags": ";".join(elements.singular_flags),
        })
    candidate_fields = ["family", "seed_index", "reference_jd_tdb", "x_au", "y_au", "z_au",
                        "vx_au_per_day", "vy_au_per_day", "vz_au_per_day", "cost", "success"]
    element_fields = ["family", "reference_jd_tdb", "semimajor_axis_au", "eccentricity", "inclination_deg",
                      "longitude_ascending_node_deg", "argument_perihelion_deg", "mean_anomaly_deg", "singular_flags"]
    candidates = output / "candidate_orbits.csv"
    elements_path = output / "orbital_elements.csv"
    _atomic_csv(candidates, candidate_fields, candidate_rows)
    _atomic_csv(elements_path, element_fields, element_rows)
    covariance_path = output / "covariance.csv"
    covariance_rows = []
    if evaluation.covariance.covariance is not None:
        for row_index, row in enumerate(evaluation.covariance.covariance):
            for column_index, value in enumerate(row):
                covariance_rows.append({"row": row_index, "column": column_index, "value": repr(float(value)),
                                        "supported": str(evaluation.covariance.supported), "reason": evaluation.covariance.reason})
    else:
        covariance_rows.append({"row": "", "column": "", "value": "",
                                "supported": str(evaluation.covariance.supported), "reason": evaluation.covariance.reason})
    _atomic_csv(covariance_path, ["row", "column", "value", "supported", "reason"], covariance_rows)
    bootstrap_path = output / "bootstrap_elements.csv"
    bootstrap_rows = []
    for index, state in enumerate(evaluation.bootstrap.states):
        elements = state_to_elements(state)
        bootstrap_rows.append({"replicate": index, "semimajor_axis_au": repr(elements.semimajor_axis_au),
                               "eccentricity": repr(elements.eccentricity), "inclination_deg": repr(elements.inclination_deg)})
    _atomic_csv(bootstrap_path, ["replicate", "semimajor_axis_au", "eccentricity", "inclination_deg"], bootstrap_rows)
    return [candidates, elements_path, covariance_path, bootstrap_path]


def _write_figures(output: Path, observations: tuple[Observation, ...], fit: OrbitFitResult, evaluation) -> list[Path]:
    sky_rows = []
    prediction_by_id = {}
    if fit.solutions:
        predicted = predict_topocentric_unit(fit.solutions[0].state, observations, light_time=True)
        prediction_by_id = {row.direction.run_id: vector for row, vector in zip(observations, predicted)}
    withheld_ids = {row.direction.run_id for row in evaluation.split.withheld}
    for row in observations:
        measured_ra, measured_dec = _radec(row.measured_unit)
        prediction = prediction_by_id.get(row.direction.run_id)
        predicted_ra, predicted_dec = _radec(prediction) if prediction is not None else (None, None)
        sky_rows.append({"run_id": row.direction.run_id, "jd_tdb": repr(row.jd_tdb),
                         "partition": "withheld" if row.direction.run_id in withheld_ids else "fit",
                         "measured_ra_icrs_deg": repr(measured_ra), "measured_dec_icrs_deg": repr(measured_dec),
                         "predicted_ra_icrs_deg": "" if predicted_ra is None else repr(predicted_ra),
                         "predicted_dec_icrs_deg": "" if predicted_dec is None else repr(predicted_dec)})
    sky_data = output / "orbit_sky_track_data.csv"
    _atomic_csv(sky_data, list(sky_rows[0]), sky_rows)
    figure, axis = plt.subplots(figsize=(8, 5))
    for partition, marker in (("fit", "o"), ("withheld", "s")):
        subset = [row for row in sky_rows if row["partition"] == partition]
        axis.scatter([float(row["measured_ra_icrs_deg"]) for row in subset],
                     [float(row["measured_dec_icrs_deg"]) for row in subset], marker=marker,
                     label=f"measured {partition}")
    predicted_rows = [row for row in sky_rows if row["predicted_ra_icrs_deg"] != ""]
    if predicted_rows:
        axis.plot([float(row["predicted_ra_icrs_deg"]) for row in predicted_rows],
                  [float(row["predicted_dec_icrs_deg"]) for row in predicted_rows], "k-", label="fitted orbit")
    else:
        axis.text(0.5, 0.5, "Orbit unresolved", transform=axis.transAxes, ha="center")
    axis.set_xlabel("ICRS right ascension (deg)")
    axis.set_ylabel("ICRS declination (deg)")
    axis.set_title(f"Object A sky track; TDB epoch near JD {fit.reference_jd_tdb:.3f}")
    handles, labels = axis.get_legend_handles_labels()
    if handles:
        axis.legend(handles, labels, loc="best")
    sky_figure = output / "orbit_sky_track.png"
    _atomic_figure(sky_figure, figure)

    residual_rows = []
    if fit.solutions:
        predicted = predict_topocentric_unit(fit.solutions[0].state, observations, light_time=True)
        residuals = tangent_residuals_arcmin(np.asarray([row.measured_unit for row in observations]), predicted)
        for row, residual in zip(observations, residuals):
            residual_rows.append({"run_id": row.direction.run_id, "jd_tdb": repr(row.jd_tdb),
                                  "east_arcmin": repr(float(residual[0])), "north_arcmin": repr(float(residual[1])),
                                  "norm_arcmin": repr(float(np.linalg.norm(residual)))})
    residual_data = output / "orbit_residuals_data.csv"
    _atomic_csv(residual_data, ["run_id", "jd_tdb", "east_arcmin", "north_arcmin", "norm_arcmin"], residual_rows)
    figure, axis = plt.subplots(figsize=(8, 5))
    if residual_rows:
        epochs = [float(row["jd_tdb"]) - fit.reference_jd_tdb for row in residual_rows]
        axis.plot(epochs, [float(row["east_arcmin"]) for row in residual_rows], "o-", label="east")
        axis.plot(epochs, [float(row["north_arcmin"]) for row in residual_rows], "o-", label="north")
        axis.plot(epochs, [float(row["norm_arcmin"]) for row in residual_rows], "k.-", label="norm")
    else:
        axis.text(0.5, 0.5, "Orbit unresolved; no residuals", transform=axis.transAxes, ha="center")
    axis.axhline(0.0, color="0.5", linewidth=0.8)
    axis.set_xlabel(f"TDB days from JD {fit.reference_jd_tdb:.6f}")
    axis.set_ylabel("Measured − predicted tangent residual (arcmin; ×1)")
    axis.set_title("Object A orbit residuals (actual scale, no cosmetic shift)")
    handles, labels = axis.get_legend_handles_labels()
    if handles:
        axis.legend(handles, labels, loc="best")
    residual_figure = output / "orbit_residuals.png"
    _atomic_figure(residual_figure, figure)

    orbit_rows = []
    if fit.solutions:
        solution = fit.solutions[0]
        period_days = 2.0 * math.pi * math.sqrt(solution.elements.semimajor_axis_au**3 / SOLAR_GM_AU3_DAY2)
        epochs = np.linspace(solution.state.reference_jd_tdb, solution.state.reference_jd_tdb + period_days, 361)
        positions = propagate_two_body(solution.state, epochs)[:, 0, :]
        orbit_rows = [{"sample": index, "jd_tdb": repr(float(epoch)), "x_au": repr(float(position[0])),
                       "y_au": repr(float(position[1])), "z_au": repr(float(position[2]))}
                      for index, (epoch, position) in enumerate(zip(epochs, positions))]
    orbit_data = output / "heliocentric_orbit_data.csv"
    _atomic_csv(orbit_data, ["sample", "jd_tdb", "x_au", "y_au", "z_au"], orbit_rows)
    figure, axis = plt.subplots(figsize=(6, 6))
    if orbit_rows:
        axis.plot([float(row["x_au"]) for row in orbit_rows], [float(row["y_au"]) for row in orbit_rows], label="Object A family 0")
    else:
        axis.text(0.5, 0.5, "Orbit unresolved", transform=axis.transAxes, ha="center")
    angle = np.linspace(0.0, 2.0 * math.pi, 361)
    axis.plot(np.cos(angle), np.sin(angle), color="tab:blue", alpha=0.5, label="1 au reference circle")
    axis.plot([0.0], [0.0], marker="*", color="gold", markersize=12, label="Sun")
    axis.set_aspect("equal", adjustable="datalim")
    axis.set_xlabel("Heliocentric ICRS x (au)")
    axis.set_ylabel("Heliocentric ICRS y (au)")
    axis.set_title(f"Osculating family at TDB JD {fit.reference_jd_tdb:.6f}")
    axis.legend(loc="best")
    orbit_figure = output / "heliocentric_orbit.png"
    _atomic_figure(orbit_figure, figure)
    return [sky_data, sky_figure, residual_data, residual_figure, orbit_data, orbit_figure]


def write_controlled_report(output: Path, extraction, fit: OrbitFitResult, evaluation) -> list[Path]:
    output = Path(output)
    if not output.is_dir():
        raise FileNotFoundError(f"report output directory does not exist: {output}")
    observations = _observations(extraction)
    if not observations:
        raise ValueError("controlled report needs observations")
    products = []
    products.extend(_write_observation_products(output, observations, evaluation))
    products.extend(_write_fit_tables(output, fit, evaluation))
    products.extend(_write_figures(output, observations, fit, evaluation))
    summary = output / "fit_summary.json"
    scores = {}
    for name, score in evaluation.scores.items():
        scores[name] = None if score is None else {
            "median_arcmin": score.median_arcmin, "rms_arcmin": score.rms_arcmin,
            "p90_arcmin": score.p90_arcmin, "weighted_chi_square": score.weighted_chi_square,
        }
    _atomic_json(summary, {
        "object_id": "Object A", "scientific_status": evaluation.scientific_status,
        "status_reason": evaluation.status_reason, "orbit_family_count": len(fit.solutions),
        "primary_sigma_scale": evaluation.primary_sigma_scale,
        "train_nights": list(evaluation.split.train_nights),
        "withheld_nights": list(evaluation.split.withheld_nights), "scores": scores,
        "covariance_supported": evaluation.covariance.supported,
        "bootstrap_requested": evaluation.bootstrap.requested_replicates,
        "bootstrap_accepted": sum(value == "accepted" for value in evaluation.bootstrap.statuses),
    })
    metadata = output / "figure_metadata.json"
    _atomic_json(metadata, {
        "orbit_sky_track": {"frame": "ICRS", "epoch_axis": "TDB Julian date", "angular_units": "degrees"},
        "orbit_residuals": {"frame": "local ICRS tangent plane", "x_units": "TDB days", "y_units": "arcmin", "residual_magnification": 1.0},
        "heliocentric_orbit": {"frame": "heliocentric ICRS", "epoch": fit.reference_jd_tdb, "units": "au"},
    })
    products.extend([summary, metadata])
    return products
