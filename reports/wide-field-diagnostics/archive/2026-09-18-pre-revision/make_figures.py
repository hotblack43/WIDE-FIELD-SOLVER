"""Reproduce the figures and numerical checks for the planetary dating draft."""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from astropy import units as u
from astropy.coordinates import EarthLocation, get_body
from astropy.time import Time
from matplotlib.lines import Line2D
from PIL import Image
from scipy.optimize import minimize_scalar


SOLVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SOLVER_ROOT))

from barghini_model import inverse_radial_u, radial_u  # noqa: E402
from point_star_barghini import BarghiniCamera  # noqa: E402


SOLUTION_DIR = Path("/tmp/wfs-espenak-2018/early-morning")
RESULT_DIR = SOLVER_ROOT / "results/espenak-early-morning-planet-spike-20260913-01"
IMAGE_PATH = Path("/home/pth/Skrivebord/StarTrails/FishEye18-1002w_Espenak.jpg")
FIGURE_DIR = Path(__file__).resolve().parent / "figures"
PUBLISHED_TIME = Time("2018-04-15T06:55:00", scale="utc")
BLIND_DATE = Time("2018-04-15", scale="tdb")
SITE = EarthLocation.from_geodetic(
    lon=-(68 + 10 / 60 + 48.7 / 3600) * u.deg,
    lat=-(22 + 57 / 60 + 9.8 / 3600) * u.deg,
    height=2400 * u.m,
)


@dataclass(frozen=True)
class PlanetPosition:
    detection_id: int
    measured_xy: np.ndarray
    predicted_xy: np.ndarray
    separation_px: float


@dataclass(frozen=True)
class PlanetDetection:
    detection_id: int
    detection_index: int
    separation_deg: float


@dataclass(frozen=True)
class AnalysisContext:
    solution: dict
    report: dict
    camera: BarghiniCamera
    detections: list[dict[str, str]]
    detection_xy: np.ndarray
    detection_sky: np.ndarray
    recoveries: list[dict]
    published_matches: dict[str, dict[str, str]]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _unit_vectors(coordinates) -> np.ndarray:
    xyz = np.asarray(coordinates.cartesian.xyz.value, dtype=float)
    if xyz.ndim == 1:
        xyz = xyz[:, None]
    xyz /= np.linalg.norm(xyz, axis=0)
    return xyz.T


def load_context() -> AnalysisContext:
    solution = json.loads((SOLUTION_DIR / "result.json").read_text())
    report = json.loads((RESULT_DIR / "report.json").read_text())
    camera_json = solution["camera"]
    camera = BarghiniCamera(
        tuple(camera_json["shape"]),
        np.asarray(camera_json["reference_rotation"], dtype=float),
        np.asarray(camera_json["normalised_parameters"], dtype=float),
    )
    detections = _read_csv(SOLUTION_DIR / "dots/star_candidates.csv")
    detection_xy = np.asarray(
        [[float(row["x_px"]), float(row["y_px"])] for row in detections]
    )
    recoveries = report["published_epoch_recovered_planets"]
    published_rows = _read_csv(RESULT_DIR / "published_epoch_planet_matches.csv")
    published_matches = {row["planet"]: row for row in published_rows}

    if solution["source_sha256"] != report["source_sha256"]:
        raise ValueError("stellar solution and planet report use different images")
    if solution["fit"]["count"] != 1213:
        raise ValueError("unexpected stellar-association count")
    if {row["planet"] for row in recoveries} != {"mars", "jupiter", "saturn"}:
        raise ValueError("expected the Mars-Jupiter-Saturn recovery")

    return AnalysisContext(
        solution=solution,
        report=report,
        camera=camera,
        detections=detections,
        detection_xy=detection_xy,
        detection_sky=camera.to_sky(detection_xy),
        recoveries=recoveries,
        published_matches=published_matches,
    )


def fitted_horizon_radius(camera: BarghiniCamera) -> float:
    parameters = camera.physical
    return float(inverse_radial_u(np.pi / 2, parameters.v, parameters.s, parameters.d))


def published_planet_positions(context: AnalysisContext) -> dict[str, PlanetPosition]:
    detection_index = {
        int(row["detection_id"]): index for index, row in enumerate(context.detections)
    }
    positions = {}
    for recovery in context.recoveries:
        planet = recovery["planet"]
        identifier = int(recovery["detection_id"])
        match = context.published_matches[planet]
        positions[planet] = PlanetPosition(
            detection_id=identifier,
            measured_xy=context.detection_xy[detection_index[identifier]].copy(),
            predicted_xy=np.asarray(
                [float(match["predicted_x_px"]), float(match["predicted_y_px"])]
            ),
            separation_px=float(recovery["pixel_separation"]),
        )
    return positions


def discover_planet_detections(
    context: AnalysisContext,
    epoch: Time,
    planet_names: tuple[str, ...],
    maximum_separation_deg: float,
) -> dict[str, PlanetDetection]:
    matches = {}
    used_detection_ids = set()
    for planet in planet_names:
        body_sky = _unit_vectors(get_body(planet, epoch, location=SITE))[0]
        separations = np.degrees(
            np.arccos(np.clip(context.detection_sky @ body_sky, -1.0, 1.0))
        )
        for index in np.argsort(separations):
            identifier = int(context.detections[int(index)]["detection_id"])
            if identifier in used_detection_ids:
                continue
            separation = float(separations[index])
            if separation > maximum_separation_deg:
                raise ValueError(
                    f"no detection within {maximum_separation_deg} deg of {planet}"
                )
            matches[planet] = PlanetDetection(identifier, int(index), separation)
            used_detection_ids.add(identifier)
            break
    return matches


def _epoch_rms(context: AnalysisContext, matches: dict[str, PlanetDetection], epoch: Time) -> float:
    square_separations = []
    for planet, match in matches.items():
        body_sky = _unit_vectors(get_body(planet, epoch, location=SITE))[0]
        cosine = np.clip(context.detection_sky[match.detection_index] @ body_sky, -1.0, 1.0)
        square_separations.append(np.degrees(np.arccos(cosine)) ** 2)
    return float(np.sqrt(np.mean(square_separations)))


def refine_epoch(
    context: AnalysisContext, matches: dict[str, PlanetDetection]
) -> tuple[Time, float]:
    result = minimize_scalar(
        lambda day_offset: _epoch_rms(
            context, matches, BLIND_DATE + day_offset * u.day
        ),
        bounds=(-2.0, 2.0),
        method="bounded",
        options={"xatol": 1.0e-10},
    )
    best_time = BLIND_DATE + float(result.x) * u.day
    return best_time, float(result.fun)


def _timing_curve(
    context: AnalysisContext,
    matches: dict[str, PlanetDetection],
    epochs: Time,
    measured_sky: np.ndarray | None = None,
) -> np.ndarray:
    if measured_sky is None:
        measured_sky = np.asarray(
            [context.detection_sky[match.detection_index] for match in matches.values()]
        )
    square_separations = np.zeros((len(epochs),), dtype=float)
    for index, planet in enumerate(matches):
        body_sky = _unit_vectors(get_body(planet, epochs, location=SITE))
        cosine = np.clip(body_sky @ measured_sky[index], -1.0, 1.0)
        square_separations += np.degrees(np.arccos(cosine)) ** 2
    return np.sqrt(square_separations / len(matches))


def _empirical_timing_sensitivity(
    context: AnalysisContext,
    matches: dict[str, PlanetDetection],
    best_time: Time,
    epochs: Time,
    bootstrap_count: int = 2000,
) -> dict[str, float]:
    star_rows = _read_csv(SOLUTION_DIR / "star_coordinates.csv")
    residual_xy = np.asarray(
        [
            [
                float(row["predicted_x_px"]) - float(row["x_px"]),
                float(row["predicted_y_px"]) - float(row["y_px"]),
            ]
            for row in star_rows
        ]
    )
    residual_xy -= np.median(residual_xy, axis=0)
    base_xy = np.asarray(
        [context.detection_xy[match.detection_index] for match in matches.values()]
    )
    rng = np.random.default_rng(20260913)
    sampled = residual_xy[
        rng.integers(0, len(residual_xy), size=(bootstrap_count, len(matches)))
    ]
    perturbed_sky = context.camera.to_sky((base_xy[None, :, :] + sampled).reshape(-1, 2))
    perturbed_sky = perturbed_sky.reshape(bootstrap_count, len(matches), 3)

    square_separations = np.zeros((bootstrap_count, len(epochs)), dtype=np.float32)
    for planet_index, planet in enumerate(matches):
        body_sky = _unit_vectors(get_body(planet, epochs, location=SITE))
        cosine = np.clip(perturbed_sky[:, planet_index, :] @ body_sky.T, -1.0, 1.0)
        square_separations += np.degrees(np.arccos(cosine)).astype(np.float32) ** 2
    best_indices = np.argmin(square_separations, axis=1)
    offsets_hours = (epochs[best_indices] - best_time).to_value(u.hour)
    q16, median, q84 = np.quantile(offsets_hours, [0.16, 0.5, 0.84])
    return {
        "bootstrap_count": bootstrap_count,
        "offset_q16_hours": float(q16),
        "offset_median_hours": float(median),
        "offset_q84_hours": float(q84),
        "boundary_fraction": float(
            np.mean((best_indices == 0) | (best_indices == len(epochs) - 1))
        ),
    }


def _make_planet_overlay(context: AnalysisContext) -> None:
    image = np.asarray(Image.open(IMAGE_PATH).convert("RGB"))
    positions = published_planet_positions(context)
    colours = {"mars": "#ff8c42", "jupiter": "#ff38d1", "saturn": "#53e66b"}

    figure = plt.figure(figsize=(12, 11.2), constrained_layout=True)
    grid = figure.add_gridspec(2, 3, height_ratios=(3.2, 1.0))
    full_axis = figure.add_subplot(grid[0, :])
    full_axis.imshow(image)
    full_axis.set_axis_off()
    full_axis.set_title("2018-04-15 06:55 UTC — Atacama Lodge, Chile", fontsize=12)

    for planet in ("mars", "jupiter", "saturn"):
        position = positions[planet]
        full_axis.scatter(
            *position.measured_xy,
            marker="o",
            facecolors="none",
            edgecolors="cyan",
            linewidths=1.8,
            s=115,
        )
        full_axis.scatter(
            *position.predicted_xy,
            marker="x",
            color=colours[planet],
            linewidths=2.1,
            s=90,
        )
        full_axis.annotate(
            planet.title(),
            position.predicted_xy,
            xytext=(7, 7),
            textcoords="offset points",
            color="white",
            fontsize=10,
            bbox={"facecolor": "black", "alpha": 0.58, "edgecolor": "none", "pad": 2},
        )

    full_axis.legend(
        handles=[
            Line2D([], [], marker="o", linestyle="none", markerfacecolor="none", markeredgecolor="cyan", markeredgewidth=1.8, markersize=9, label="Detected position"),
            Line2D([], [], marker="x", linestyle="none", color="#ff38d1", markeredgewidth=2.0, markersize=9, label="Predicted position"),
        ],
        loc="lower right",
        framealpha=0.82,
        fontsize=9,
    )

    zoom_half_width = {"mars": 13, "jupiter": 13, "saturn": 13}
    for column, planet in enumerate(("mars", "jupiter", "saturn")):
        axis = figure.add_subplot(grid[1, column])
        position = positions[planet]
        centre = (position.measured_xy + position.predicted_xy) / 2
        half_width = zoom_half_width[planet]
        axis.imshow(image)
        axis.scatter(*position.measured_xy, marker="o", facecolors="none", edgecolors="cyan", linewidths=2.0, s=190)
        axis.scatter(*position.predicted_xy, marker="x", color=colours[planet], linewidths=2.4, s=130)
        axis.set_xlim(centre[0] - half_width, centre[0] + half_width)
        axis.set_ylim(centre[1] + half_width, centre[1] - half_width)
        axis.set_title(f"{planet.title()} — {position.separation_px:.3f} px", fontsize=10)
        axis.set_xlabel("x [pixel]")
        if column == 0:
            axis.set_ylabel("y [pixel]")

    figure.suptitle("Planets in Espenak’s early-morning fisheye image", fontsize=16)
    figure.savefig(FIGURE_DIR / "planet_measured_vs_predicted_overlay.png", dpi=200)
    plt.close(figure)


def _make_lens_epoch_figure(
    context: AnalysisContext,
    matches: dict[str, PlanetDetection],
    best_time: Time,
    best_rms: float,
) -> tuple[dict[str, float], dict[str, float]]:
    parameters = context.camera.physical
    horizon_radius = fitted_horizon_radius(context.camera)
    radius = np.linspace(0.0, horizon_radius, 500)
    fitted_angle = np.degrees(radial_u(radius, parameters.v, parameters.s, parameters.d))
    equidistant_angle = 90.0 * radius / horizon_radius

    daily_rows = _read_csv(RESULT_DIR / "blind_pair_daily.csv")
    daily_dates = np.asarray(
        [np.datetime64(row["date_tdb"]) for row in daily_rows]
    )
    daily_rms = np.asarray(
        [float(row["best_distinct_pair_rms_deg"]) for row in daily_rows]
    )

    curve_epochs = PUBLISHED_TIME + np.linspace(-2.0, 2.0, 1153) * u.day
    curve_rms = _timing_curve(context, matches, curve_epochs)
    below = curve_rms < 0.1
    timing_profile = {
        "rms_below_0_1_deg_width_hours": float(
            (curve_epochs[np.flatnonzero(below)[-1]] - curve_epochs[np.flatnonzero(below)[0]]).to_value(u.hour)
        ),
        "published_epoch_rms_deg": float(_epoch_rms(context, matches, PUBLISHED_TIME)),
        "best_epoch_rms_deg": best_rms,
    }

    bootstrap_epochs = best_time + np.linspace(-2.0, 2.0, 1153) * u.day
    sensitivity = _empirical_timing_sensitivity(
        context, matches, best_time, bootstrap_epochs
    )

    figure, axes = plt.subplots(1, 2, figsize=(12.4, 4.8), constrained_layout=True)
    axis = axes[0]
    axis.plot(radius, fitted_angle, linewidth=2.0, label="Fitted Barghini mapping")
    axis.plot(radius, equidistant_angle, linestyle="--", linewidth=1.6, label="Equidistant mapping")
    axis.set_xlabel("Radius from fitted optical centre [pixel]")
    axis.set_ylabel("Field angle [deg]")
    axis.set_title("Lens mapping")
    axis.legend(loc="upper left")
    axis.text(
        0.04,
        0.72,
        f"Optical centre: ({parameters.x_o:.2f}, {parameters.y_o:.2f}) px\n"
        f"90° radius: {horizon_radius:.2f} px\n"
        f"Central scale: {np.degrees(parameters.v + parameters.s * parameters.d):.4f}° px⁻¹",
        transform=axis.transAxes,
        fontsize=9,
        bbox={"facecolor": "white", "alpha": 0.82, "edgecolor": "0.75"},
    )

    axis = axes[1]
    axis.plot(daily_dates, np.minimum(daily_rms, 1.0), color="0.55", linewidth=0.45)
    best_daily_index = int(np.argmin(daily_rms))
    axis.scatter(daily_dates[best_daily_index], daily_rms[best_daily_index], color="#d95f02", zorder=3)
    axis.annotate(
        "2018-04-15",
        (daily_dates[best_daily_index], daily_rms[best_daily_index]),
        xytext=(-46, 18),
        textcoords="offset points",
        arrowprops={"arrowstyle": "->", "color": "#d95f02"},
    )
    axis.set_xlabel("Candidate date")
    axis.set_ylabel("Best two-planet RMS [deg]")
    axis.set_ylim(0.0, 1.02)
    axis.set_title("Blind planetary search, 1950–2026")
    axis.xaxis.set_major_locator(mdates.YearLocator(15))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    inset = axis.inset_axes([0.08, 0.53, 0.48, 0.40])
    inset.plot(curve_epochs.utc.datetime, curve_rms, color="#1b9e77", linewidth=1.3)
    inset.axvline(PUBLISHED_TIME.utc.datetime, color="black", linestyle="--", linewidth=0.9)
    inset.axvline(best_time.utc.datetime, color="#d95f02", linewidth=1.0)
    inset.axhline(0.1, color="0.5", linestyle=":", linewidth=0.8)
    inset.set_xlim((PUBLISHED_TIME - 0.7 * u.day).utc.datetime, (PUBLISHED_TIME + 0.7 * u.day).utc.datetime)
    inset.set_ylim(0.04, 0.12)
    inset.xaxis.set_major_locator(mdates.HourLocator(interval=12))
    inset.xaxis.set_major_formatter(mdates.DateFormatter("%d %Hh"))
    inset.tick_params(labelsize=7)
    inset.set_ylabel("3-planet RMS [deg]", fontsize=7)
    inset.set_title("Sub-day minimum", fontsize=8)

    figure.savefig(FIGURE_DIR / "lens_and_epoch_solution.pdf")
    figure.savefig(FIGURE_DIR / "lens_and_epoch_solution.png", dpi=180)
    plt.close(figure)
    return timing_profile, sensitivity


def main() -> None:
    FIGURE_DIR.mkdir(exist_ok=True)
    context = load_context()
    blind_matches = discover_planet_detections(
        context,
        BLIND_DATE,
        ("mars", "jupiter", "saturn"),
        maximum_separation_deg=0.25,
    )
    best_time, best_rms = refine_epoch(context, blind_matches)
    _make_planet_overlay(context)
    timing_profile, sensitivity = _make_lens_epoch_figure(
        context, blind_matches, best_time, best_rms
    )
    summary = {
        "blind_date_tdb": BLIND_DATE.tdb.isot,
        "blind_date_detection_ids": {
            planet: match.detection_id for planet, match in blind_matches.items()
        },
        "best_epoch_utc": best_time.utc.isot,
        "best_epoch_rms_deg": best_rms,
        "offset_from_published_minutes": float((best_time - PUBLISHED_TIME).to_value(u.min)),
        "fitted_horizon_radius_px": fitted_horizon_radius(context.camera),
        "timing_profile": timing_profile,
        "empirical_timing_sensitivity": sensitivity,
    }
    (Path(__file__).resolve().parent / "analysis_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
