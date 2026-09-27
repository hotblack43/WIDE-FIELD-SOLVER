#!/usr/bin/env python3
"""Extract and plot planet instrumental photometry from the run database."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import csv
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PLANET_TYPES = {"major_planet", "minor_planet"}
DETECTION_STATUSES = {"metadata_time_match", "selected_planet_match"}
CSV_FIELDS = [
    "run_id", "recorded_at_utc", "source_path", "source_sha256",
    "catalogue_sha256",
    "observation_time_utc", "camera_label", "camera_provenance",
    "planet_type", "planet", "identity_status",
    "candidate_rank", "detection_id", "source_class", "channel",
    "exposure_seconds", "exposure_source", "count_rate_adu_per_s", "machine_magnitude",
    "planet_measured_altitude_deg", "planet_airmass",
    "stellar_intercept_mag", "stellar_extinction_mag_per_airmass",
    "stellar_calibration_offset_mag", "stellar_fit_rms_mag", "stellar_fit_count",
    "stellar_fit_status", "stellar_catalogue_passband",
    "stellar_calibration_status", "stellar_calibration_source",
    "photometry_usable", "exclusion_reason", "saturation_known",
    "channel_saturated", "measurement_method", "row_number",
]
PLANET_COLOURS = {
    "Mercury": "#7f7f7f",
    "Venus": "#bcbd22",
    "Mars": "#d62728",
    "Jupiter": "#ff7f0e",
    "Saturn": "#8c564b",
    "Uranus": "#17becf",
    "Neptune": "#1f77b4",
    "Ceres": "#9467bd",
    "Vesta": "#e377c2",
}
PREFERRED_CAMERA_MARKERS = {
    "APICAM": "s",
    "MMTO skycam": "o",
    "Subaru/Maunakea skycam": "^",
    "Nikon D750 / Espenak": "D",
    "Olympus E-M1 Mark II": "P",
}
AVAILABLE_CAMERA_MARKERS = ["o", "s", "^", "D", "v", "P", "X", "<", ">", "h", "p", "*", "8"]
EXPOSURE_AUDIT_FIELDS = [
    "source_path", "source_sha256", "source_present", "checksum_status",
    "source_format", "search_status", "accepted_source_seconds",
    "accepted_source_provenance", "database_exposure_seconds",
    "database_exposure_sources", "candidates_json", "examined_metadata_json",
]
HORIZONS_API = "https://ssd.jpl.nasa.gov/api/horizons.api"
HORIZONS_TARGETS = {
    "Mercury": "199", "Venus": "299", "Mars": "499", "Jupiter": "599",
    "Saturn": "699", "Uranus": "799", "Neptune": "899",
    "Ceres": "1;", "Vesta": "4;",
}
DISTANCE_CORRECTED_FIELDS = [
    *CSV_FIELDS,
    "sun_planet_distance_au", "earth_planet_distance_au",
    "distance_correction_mag", "distance_corrected_magnitude",
    "distance_ephemeris_source", "count_rate_uncertainty_adu_per_s",
    "machine_magnitude_uncertainty", "background_noise_adu",
    "aperture_pixels", "background_annulus_pixels",
    "uncertainty_status", "uncertainty_source",
]
STELLAR_CALIBRATED_DISTANCE_FIELDS = [
    *DISTANCE_CORRECTED_FIELDS,
    "stellar_calibrated_magnitude",
    "stellar_calibrated_distance_magnitude",
    "stellar_fit_uncertainty_mag",
    "total_magnitude_uncertainty",
]
EXTINCTION_CORRECTED_DISTANCE_FIELDS = [
    *DISTANCE_CORRECTED_FIELDS,
    "stellar_only_fit_rms_arcmin",
    "metadata_association_status",
    "metadata_association_time_utc",
    "metadata_association_epoch_tdb",
    "metadata_association_epoch_source",
    "metadata_association_method",
    "metadata_association_jd_tdb",
    "association_gate_arcmin",
    "association_positional_sigma_arcmin",
    "association_measured_x_px",
    "association_measured_y_px",
    "association_predicted_x_px",
    "association_predicted_y_px",
    "association_separation_px",
    "association_separation_arcmin",
    "association_catalogue_residual_px",
    "association_catalogue_residual_arcmin",
    "nightly_extinction_night",
    "nightly_extinction_mag_per_airmass",
    "nightly_extinction_scaled_mad",
    "nightly_zero_point_mag",
    "nightly_zero_point_uncertainty_mag",
    "extinction_corrected_magnitude",
    "extinction_corrected_distance_magnitude",
    "extinction_correction_status",
    "extinction_correction_source",
    "nightly_extinction_uncertainty_mag",
    "total_magnitude_uncertainty",
    "extinction_correction_exclusion_reason",
]


def _readonly_database(database):
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mmto_observing_night(observation_time_utc):
    normalized = _normalise_utc(observation_time_utc)
    if normalized is None:
        return None
    observed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    local = observed.astimezone(ZoneInfo("America/Phoenix"))
    night = local.date()
    if local.hour < 12:
        night -= timedelta(days=1)
    return night.isoformat()


def load_nightly_image_calibrations(directory):
    """Load unique accepted reference coefficients and fixed image zero points."""
    directory = Path(directory).expanduser().resolve()
    coefficient_path = directory / "nightly_extinction_coefficients.csv"
    zero_point_path = directory / "image_zero_points.csv"
    coefficients = {}
    seen_coefficients = set()
    with coefficient_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("model") != "reference_ols":
                continue
            coefficient_key = (
                row.get("catalogue_sha256", ""),
                row.get("night", ""),
                row.get("channel", ""),
            )
            if coefficient_key in seen_coefficients:
                raise ValueError(
                    "duplicate nightly reference coefficient for "
                    + "/".join(coefficient_key)
                )
            seen_coefficients.add(coefficient_key)
            if row.get("status") != "accepted":
                continue
            extinction = _finite(row.get("extinction_mag_per_airmass"))
            scaled_mad = _finite(row.get("scaled_mad_mag_per_airmass"))
            if extinction is None or scaled_mad is None or scaled_mad < 0.0:
                raise ValueError(
                    "accepted nightly coefficient is incomplete for "
                    + "/".join(coefficient_key)
                )
            coefficients[coefficient_key] = {
                "extinction_mag_per_airmass": extinction,
                "extinction_scaled_mad": scaled_mad,
            }

    calibrations = {}
    seen_zero_points = set()
    with zero_point_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("model") != "reference_ols":
                continue
            key = (
                row.get("source_sha256", ""),
                row.get("catalogue_sha256", ""),
                row.get("night", ""),
                row.get("channel", ""),
            )
            if key in seen_zero_points:
                raise ValueError("duplicate image zero point for " + "/".join(key))
            seen_zero_points.add(key)
            if row.get("status") != "accepted":
                continue
            coefficient_key = (key[1], key[2], key[3])
            coefficient = coefficients.get(coefficient_key)
            if coefficient is None:
                raise ValueError(
                    "accepted image zero point has no accepted nightly coefficient for "
                    + "/".join(key)
                )
            zero_point = _finite(row.get("zero_point_magnitude"))
            zero_uncertainty = _finite(row.get("uncertainty_magnitude"))
            saved_extinction = _finite(row.get("extinction_mag_per_airmass"))
            observed_utc = _normalise_utc(row.get("observed_utc"))
            if (
                zero_point is None
                or zero_uncertainty is None
                or zero_uncertainty < 0.0
                or saved_extinction is None
                or observed_utc is None
                or not math.isclose(
                    saved_extinction,
                    coefficient["extinction_mag_per_airmass"],
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError(
                    "accepted image zero point is incomplete or inconsistent for "
                    + "/".join(key)
                )
            calibrations[key] = {
                **coefficient,
                "observed_utc": observed_utc,
                "zero_point_magnitude": zero_point,
                "zero_point_uncertainty_magnitude": zero_uncertainty,
                "extinction_correction_source": str(directory),
            }
    return calibrations


def _load_module_from_path(name, path):
    """Load one preserved-runtime module under an isolated private name."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load preserved module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


@lru_cache(maxsize=1)
def _v11_metadata_planet_tools():
    """Return the frozen v11 camera, association, and ephemeris functions."""
    version = ROOT / "v11"
    modules_before = set(sys.modules)
    barghini = _load_module_from_path(
        "_mmto_v11_barghini_model", version / "barghini_model.py"
    )
    previous_barghini = sys.modules.get("barghini_model")
    sys.modules["barghini_model"] = barghini
    sys.path.insert(0, str(version))
    try:
        camera_module = _load_module_from_path(
            "_mmto_v11_point_star_barghini", version / "point_star_barghini.py"
        )
    finally:
        try:
            sys.path.remove(str(version))
        except ValueError:
            pass
        if previous_barghini is None:
            sys.modules.pop("barghini_model", None)
        else:
            sys.modules["barghini_model"] = previous_barghini
        for module_name in set(sys.modules) - modules_before:
            loaded = sys.modules.get(module_name)
            loaded_path = getattr(loaded, "__file__", None)
            if (
                loaded_path
                and Path(loaded_path).resolve().is_relative_to(version.resolve())
                and not module_name.startswith("_mmto_v11_")
            ):
                sys.modules.pop(module_name, None)
    planet_module = _load_module_from_path(
        "_mmto_v11_point_star_planets", version / "point_star_planets.py"
    )
    ephemeris_module = _load_module_from_path(
        "_mmto_v11_point_star_planet_ephemeris",
        version / "point_star_planet_ephemeris.py",
    )
    return (
        camera_module.BarghiniCamera,
        planet_module.associate_planets_at_metadata_time,
        ephemeris_module.PLANETS,
        ephemeris_module.planet_vectors,
    )


def _associate_saved_mmto_planets(
    camera_record,
    detections,
    zenith_unit_vector,
    observed_utc,
    positional_sigma_arcmin,
):
    """Associate saved detections at downstream MMTO manifest time."""
    from astropy.time import Time

    camera_class, associate, planet_names, vector_function = (
        _v11_metadata_planet_tools()
    )
    camera = camera_class.from_serialised(camera_record)
    observed = datetime.fromisoformat(observed_utc.replace("Z", "+00:00"))
    metadata = {
        "status": "selected",
        "jd_tdb": float(Time(observed).tdb.jd),
        "time_utc": observed_utc,
        "source": "MMTO downloader manifest observed_utc (downstream only)",
    }
    return associate(
        camera,
        detections,
        planet_names,
        vector_function,
        metadata,
        positional_sigma_arcmin=positional_sigma_arcmin,
        zenith_unit_vector=zenith_unit_vector,
    )


def _measurement_rows(connection, run_id, product):
    rows = []
    for row_number, star_id, detection_id, payload in connection.execute(
        """SELECT row_number,star_id,detection_id,values_json
           FROM measurements WHERE run_id=? AND product=? ORDER BY row_number""",
        (run_id, product),
    ):
        try:
            values = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(values, dict):
            continue
        values = dict(values)
        values.setdefault("detection_id", str(detection_id or ""))
        values["_row_number"] = row_number
        values["_star_id"] = str(star_id or "")
        rows.append(values)
    return rows


def load_mmto_metadata_planet_measurements(
    database,
    nightly_calibration,
    channel="G",
    *,
    association_provider=None,
):
    """Re-identify planets at MMTO manifest UTC from immutable saved products.

    This is a downstream, metadata-conditioned association.  It never changes
    the blind solution or writes to the run database.
    """
    if channel not in {"R", "G", "B"}:
        raise ValueError("channel must be R, G or B")
    calibrations = load_nightly_image_calibrations(nightly_calibration)
    selected_calibrations = {}
    for key, calibration in calibrations.items():
        source_sha256, catalogue_sha256, night, saved_channel = key
        if saved_channel != channel:
            continue
        pair = source_sha256, catalogue_sha256
        if pair in selected_calibrations:
            raise ValueError(
                "multiple accepted sidecar rows for source/catalogue/channel "
                + "/".join((*pair, channel))
            )
        selected_calibrations[pair] = (night, calibration)

    associate = association_provider or _associate_saved_mmto_planets
    audit = Counter()
    rows = []
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        latest = {}
        for run in connection.execute(
            """SELECT run_id,recorded_at_utc,source_path,source_sha256,
                      catalogue_sha256,exit_code
               FROM runs ORDER BY recorded_at_utc,run_id"""
        ):
            if int(run[5]) != 0:
                continue
            pair = str(run[3] or ""), str(run[4] or "")
            if pair in selected_calibrations:
                latest[pair] = run
        audit["accepted_sidecar_images"] = len(selected_calibrations)
        audit["selected_latest_successful_runs"] = len(latest)
        audit["accepted_sidecar_images_without_successful_run"] = (
            len(selected_calibrations) - len(latest)
        )

        for pair in sorted(latest):
            run_id, recorded, source_path, source_sha256, catalogue_sha256, _ = (
                latest[pair]
            )
            _, calibration = selected_calibrations[pair]

            def product(name):
                saved = connection.execute(
                    "SELECT content FROM products WHERE run_id=? AND product=?",
                    (run_id, name),
                ).fetchone()
                return saved[0] if saved else None

            camera_payload = product("stellar_only_result.json")
            zenith_payload = product(
                "stellar_only_products/photometric_zenith.json"
            )
            coordinate_product = "stellar_only_products/star_coordinates.csv"
            if zenith_payload is None:
                zenith_payload = product("photometric_zenith.json")
                coordinate_product = "star_coordinates.csv"
                audit["root_auxiliary_product_fallback_images"] += 1
            if camera_payload is None or zenith_payload is None:
                audit["images_missing_fixed_geometry"] += 1
                continue
            try:
                fixed_result = json.loads(camera_payload)
                camera_record = fixed_result["camera"]
                stellar_fit_rms = _finite(
                    (fixed_result.get("fit") or {}).get("rms_arcmin")
                )
                zenith = json.loads(zenith_payload)["zenith_unit_vector"]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                audit["images_with_invalid_fixed_geometry"] += 1
                continue
            if stellar_fit_rms is None or stellar_fit_rms < 0.0:
                audit["images_with_invalid_stellar_fit_rms"] += 1
                continue
            positional_sigma = max(stellar_fit_rms, 3.0)

            detections = _measurement_rows(
                connection, run_id, "dots/star_candidates.csv"
            )
            coordinates = {
                str(item.get("detection_id", "")): item
                for item in _measurement_rows(
                    connection, run_id, coordinate_product
                )
            }
            for detection in detections:
                coordinate = coordinates.get(str(detection["detection_id"]))
                if coordinate is None:
                    continue
                detection["catalogue_star_id"] = (
                    coordinate.get("star_id") or coordinate.get("_star_id")
                )
                detection["catalogue_residual_px"] = coordinate.get(
                    "residual_px"
                )
                detection["catalogue_residual_arcmin"] = coordinate.get(
                    "residual_arcmin"
                )
            photometry = {
                str(item.get("detection_id", "")): item
                for item in _measurement_rows(
                    connection, run_id, "source_photometry.csv"
                )
            }
            try:
                association = associate(
                    camera_record,
                    detections,
                    zenith,
                    calibration["observed_utc"],
                    positional_sigma,
                )
            except (ImportError, KeyError, TypeError, ValueError):
                audit["images_with_association_error"] += 1
                continue
            status = str(association.get("status", "unspecified"))
            association_time = _normalise_utc(association.get("time_utc"))
            audit[f"association_{status}_images"] += 1
            audit["metadata_time_predicted_without_source"] += len(
                association.get("predicted_without_source") or []
            )
            camera_label, camera_provenance = _camera_identity(source_path)
            for match in association.get("matches") or []:
                audit["detected_planet_rows"] += 1
                detection_id = str(match.get("detection_id", ""))
                values = photometry.get(detection_id)
                if values is None:
                    values = {}
                    rate, magnitude, reason = (
                        None,
                        None,
                        "missing_source_photometry",
                    )
                else:
                    exposure_seconds = _finite(values.get("exposure_seconds"))
                    rate, magnitude, reason = _quality(
                        values, channel, exposure_seconds=exposure_seconds
                    )
                exposure_seconds = _finite(values.get("exposure_seconds"))
                altitude = _finite(match.get("measured_altitude_deg"))
                airmass = _kasten_young_airmass(altitude)
                if altitude is None or airmass is None:
                    magnitude = None
                    reason = "planet_altitude_invalid"
                usable = not reason
                audit[
                    "usable_photometry_rows"
                    if usable
                    else "unusable_photometry_rows"
                ] += 1
                if reason:
                    audit[f"excluded_{reason}"] += 1
                planet = str(match.get("planet", ""))
                rows.append({
                    "run_id": run_id,
                    "recorded_at_utc": recorded,
                    "source_path": source_path,
                    "source_sha256": source_sha256 or "",
                    "catalogue_sha256": catalogue_sha256 or "",
                    "observation_time_utc": association_time or "",
                    "camera_label": camera_label,
                    "camera_provenance": camera_provenance,
                    "planet_type": (
                        "minor_planet"
                        if planet.casefold() in {"ceres", "vesta"}
                        else "major_planet"
                    ),
                    "planet": planet,
                    "identity_status": "metadata_time_match",
                    "candidate_rank": match.get("unused_brightness_rank", ""),
                    "detection_id": detection_id,
                    "source_class": (
                        match.get("source_class")
                        or values.get("source_class", "")
                    ),
                    "channel": channel,
                    "exposure_seconds": exposure_seconds,
                    "exposure_source": values.get("exposure_source", ""),
                    "count_rate_adu_per_s": rate,
                    "machine_magnitude": magnitude,
                    "planet_measured_altitude_deg": altitude,
                    "planet_airmass": airmass,
                    "stellar_intercept_mag": None,
                    "stellar_extinction_mag_per_airmass": None,
                    "stellar_calibration_offset_mag": None,
                    "stellar_fit_rms_mag": None,
                    "stellar_fit_count": None,
                    "stellar_fit_status": "",
                    "stellar_catalogue_passband": "",
                    "stellar_calibration_status": (
                        "not_used_extinction_sidecar_applied_downstream"
                    ),
                    "stellar_calibration_source": "",
                    "photometry_usable": usable,
                    "exclusion_reason": reason,
                    "saturation_known": values.get("saturation_known", ""),
                    "channel_saturated": values.get(
                        f"{channel}_saturated", ""
                    ),
                    "measurement_method": values.get(
                        f"{channel}_measurement_method", ""
                    ),
                    "row_number": values.get("_row_number", ""),
                    "stellar_only_fit_rms_arcmin": stellar_fit_rms,
                    "metadata_association_status": status,
                    "metadata_association_time_utc": association_time or "",
                    "metadata_association_epoch_tdb": association.get(
                        "epoch_tdb", ""
                    ),
                    "metadata_association_epoch_source": association.get(
                        "epoch_source", ""
                    ),
                    "metadata_association_method": association.get(
                        "method", ""
                    ),
                    "metadata_association_jd_tdb": match.get("jd_tdb", ""),
                    "association_gate_arcmin": association.get(
                        "gate_arcmin", ""
                    ),
                    "association_positional_sigma_arcmin": association.get(
                        "positional_sigma_arcmin", positional_sigma
                    ),
                    "association_measured_x_px": match.get(
                        "measured_x_px", ""
                    ),
                    "association_measured_y_px": match.get(
                        "measured_y_px", ""
                    ),
                    "association_predicted_x_px": match.get(
                        "predicted_x_px", ""
                    ),
                    "association_predicted_y_px": match.get(
                        "predicted_y_px", ""
                    ),
                    "association_separation_px": match.get(
                        "separation_px", ""
                    ),
                    "association_separation_arcmin": match.get(
                        "separation_arcmin", ""
                    ),
                    "association_catalogue_residual_px": match.get(
                        "catalogue_residual_px", ""
                    ),
                    "association_catalogue_residual_arcmin": match.get(
                        "catalogue_residual_arcmin", ""
                    ),
                })
        connection.rollback()
    rows.sort(
        key=lambda row: (
            row["observation_time_utc"],
            row["planet"],
            str(row["detection_id"]),
        )
    )
    audit["planet_counts"] = dict(Counter(row["planet"] for row in rows))
    audit["usable_planet_counts"] = dict(
        Counter(row["planet"] for row in rows if row["photometry_usable"])
    )
    return rows, dict(audit)


def _distance_corrected_magnitude(machine_magnitude, sun_planet_au, earth_planet_au):
    """Normalize inverse-square illumination and propagation to 1 AU each."""
    magnitude = _finite(machine_magnitude)
    r_sun = _finite(sun_planet_au)
    r_earth = _finite(earth_planet_au)
    if magnitude is None or r_sun is None or r_earth is None:
        return None
    if r_sun <= 0 or r_earth <= 0:
        return None
    return magnitude - 5.0 * math.log10(r_sun * r_earth)


def _kasten_young_airmass(altitude_deg):
    """Return Kasten-Young relative optical airmass for a visible source."""
    altitude = _finite(altitude_deg)
    if altitude is None or altitude < 0.0 or altitude > 90.0:
        return None
    zenith_distance = 90.0 - altitude
    denominator = (
        math.cos(math.radians(zenith_distance))
        + 0.50572 * (96.07995 - zenith_distance) ** -1.6364
    )
    return 1.0 / denominator


def _stellar_calibrated_distance_magnitude(
    machine_magnitude,
    intercept_mag,
    extinction_mag_per_airmass,
    altitude_deg,
    sun_planet_au,
    earth_planet_au,
):
    """Apply the saved stellar relation, then normalize both planet ranges."""
    magnitude = _finite(machine_magnitude)
    intercept = _finite(intercept_mag)
    extinction = _finite(extinction_mag_per_airmass)
    airmass = _kasten_young_airmass(altitude_deg)
    if None in (magnitude, intercept, extinction, airmass):
        return None
    calibrated = magnitude - (intercept + extinction * airmass)
    return _distance_corrected_magnitude(
        calibrated, sun_planet_au, earth_planet_au
    )


def _background_only_aperture_uncertainty(pixels, *, x, y, aperture_radius):
    """Estimate aperture-count uncertainty from robust local background noise."""
    import numpy as np

    values = np.asarray(pixels, dtype=float)
    if values.ndim != 2:
        raise ValueError("pixels must be a two-dimensional array")
    inner, outer = aperture_radius + 3.0, aperture_radius + 7.0
    height, width = values.shape
    half = int(math.ceil(outer)) + 1
    ix, iy = int(round(x)), int(round(y))
    x0, x1 = max(0, ix - half), min(width, ix + half + 1)
    y0, y1 = max(0, iy - half), min(height, iy + half + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    radius = np.hypot(xx - x, yy - y)
    cutout = values[y0:y1, x0:x1]
    finite = np.isfinite(cutout)
    aperture = (radius <= aperture_radius) & finite
    annulus = (radius >= inner) & (radius <= outer) & finite
    aperture_pixels = int(aperture.sum())
    annulus_pixels = int(annulus.sum())
    if aperture_pixels < 1 or annulus_pixels < 3:
        return None
    background = float(np.median(cutout[annulus]))
    noise = float(1.4826 * np.median(np.abs(cutout[annulus] - background)))
    if not math.isfinite(noise) or noise <= 0:
        return None
    variance_factor = (
        aperture_pixels
        + (math.pi / 2.0) * aperture_pixels ** 2 / annulus_pixels
    )
    return {
        "aperture_pixels": aperture_pixels,
        "background_annulus_pixels": annulus_pixels,
        "aperture_background_adu": background,
        "aperture_counts_adu": float(
            np.sum(cutout[aperture]) - background * aperture_pixels
        ),
        "background_noise_adu": noise,
        "flux_uncertainty_adu": noise * math.sqrt(variance_factor),
    }


def _parse_horizons_distance_response(response_text):
    """Parse JPL Horizons quantities 19 and 20: heliocentric r and observer delta."""
    text = str(response_text)
    if "$$SOE" not in text or "$$EOE" not in text:
        raise ValueError("Horizons response has no ephemeris data block")
    body = text.split("$$SOE", 1)[1].split("$$EOE", 1)[0]
    records = []
    for line in body.splitlines():
        if not line.strip():
            continue
        columns = [value.strip() for value in line.split(",")]
        if len(columns) < 6:
            raise ValueError("Horizons distance row is incomplete")
        jd = _finite(columns[0])
        r_sun = _finite(columns[3])
        r_earth = _finite(columns[5])
        if jd is None or r_sun is None or r_earth is None:
            raise ValueError("Horizons distance row is not finite")
        if r_sun <= 0 or r_earth <= 0:
            raise ValueError("Horizons distances must be positive")
        records.append((jd, r_sun, r_earth))
    if not records:
        raise ValueError("Horizons response contains no distance rows")
    return records


def _horizons_distance_lookup(rows, *, timeout=120):
    """Fetch exact-date heliocentric and geocentric ranges from JPL Horizons."""
    from astropy.time import Time
    import requests

    grouped = {}
    for row in rows:
        grouped.setdefault(row["planet"], set()).add(row["observation_time_utc"])
    lookup = {}
    source = (
        "NASA/JPL Horizons API quantities 19/20; Earth geocenter; "
        "apparent light-time-aberrated ranges"
    )
    with requests.Session() as session:
        for planet, times_set in sorted(grouped.items()):
            if planet not in HORIZONS_TARGETS:
                raise ValueError(f"No Horizons target code for {planet!r}")
            times = sorted(times_set)
            for first in range(0, len(times), 50):
                batch_times = times[first:first + 50]
                julian_dates = Time(batch_times, scale="utc").jd
                parameters = {
                    "format": "text",
                    "COMMAND": f"'{HORIZONS_TARGETS[planet]}'",
                    "OBJ_DATA": "'NO'",
                    "MAKE_EPHEM": "'YES'",
                    "EPHEM_TYPE": "'OBSERVER'",
                    "CENTER": "'500@399'",
                    "TIME_TYPE": "'UT'",
                    "TLIST": "'" + " ".join(
                        f"{value:.9f}" for value in julian_dates
                    ) + "'",
                    "TLIST_TYPE": "'JD'",
                    "CAL_FORMAT": "'JD'",
                    "QUANTITIES": "'19,20'",
                    "CSV_FORMAT": "'YES'",
                }
                response = session.get(
                    HORIZONS_API, params=parameters, timeout=timeout
                )
                response.raise_for_status()
                received = _parse_horizons_distance_response(response.text)
                if len(received) != len(batch_times):
                    raise ValueError(
                        f"Horizons returned {len(received)} rows for "
                        f"{len(batch_times)} {planet} dates"
                    )
                for time_utc, requested_jd, result in zip(
                    batch_times, julian_dates, received
                ):
                    returned_jd, r_sun, r_earth = result
                    if not math.isclose(
                        float(requested_jd), returned_jd,
                        rel_tol=0.0, abs_tol=5e-8,
                    ):
                        raise ValueError(
                            f"Horizons returned the wrong date for {planet}"
                        )
                    lookup[(planet, time_utc)] = {
                        "jd_utc": returned_jd,
                        "sun_planet_distance_au": r_sun,
                        "earth_planet_distance_au": r_earth,
                        "distance_ephemeris_source": source,
                    }
    return lookup


def _fits_channel_pixels(source_path, channel):
    """Read a native FITS channel without display scaling or normalization."""
    import numpy as np
    from astropy.io import fits

    index = {"R": 0, "G": 1, "B": 2}[channel]
    with fits.open(source_path, memmap=False) as hdus:
        arrays = [hdu.data for hdu in hdus if hdu.data is not None]
        if not arrays:
            raise ValueError("FITS source has no image array")
        data = np.asarray(arrays[0], dtype=float)
    if data.ndim == 2:
        return data
    if data.ndim != 3:
        raise ValueError("FITS image must be two- or three-dimensional")
    if 3 <= data.shape[0] <= 4:
        return data[index]
    if 3 <= data.shape[-1] <= 4:
        return data[..., index]
    raise ValueError("FITS channel axis is not identifiable")


def _file_matches_sha256(source_path, expected_sha256):
    expected = str(expected_sha256 or "").casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        return False
    digest = hashlib.sha256()
    with Path(source_path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == expected


def _photometric_uncertainty_lookup(rows, database, *, channel):
    """Reproduce saved apertures and derive empirical background-only errors."""
    geometry = {}
    with closing(_readonly_database(database)) as connection:
        for run_id in sorted({row["run_id"] for row in rows}):
            query = connection.execute(
                """SELECT detection_id,values_json FROM measurements
                   WHERE run_id=? AND product='dots/star_candidates.csv'""",
                (run_id,),
            )
            for detection_id, payload in query:
                values = json.loads(payload)
                x = _finite(values.get("x_px"))
                y = _finite(values.get("y_px"))
                sigma = _finite(values.get("major_sigma_px"))
                if x is not None and y is not None and sigma is not None and sigma > 0:
                    geometry[(run_id, str(detection_id))] = (
                        x, y, min(9.0, max(3.0, 2.5 * sigma))
                    )

    lookup = {}
    grouped = {}
    for row in rows:
        grouped.setdefault(
            (row["source_path"], row["source_sha256"]), []
        ).append(row)
    for (source_path, source_sha256), source_rows in grouped.items():
        path = Path(source_path)
        suffixes = {suffix.casefold() for suffix in path.suffixes}
        if not path.is_file():
            for row in source_rows:
                lookup[(row["run_id"], str(row["detection_id"]))] = {
                    "uncertainty_status": "source_missing"
                }
            continue
        if not _file_matches_sha256(path, source_sha256):
            for row in source_rows:
                lookup[(row["run_id"], str(row["detection_id"]))] = {
                    "uncertainty_status": "source_checksum_mismatch"
                }
            continue
        if not suffixes.intersection({".fits", ".fit", ".fts"}):
            for row in source_rows:
                lookup[(row["run_id"], str(row["detection_id"]))] = {
                    "uncertainty_status": "unsupported_source_format"
                }
            continue
        try:
            pixels = _fits_channel_pixels(path, channel)
        except (OSError, ValueError, TypeError):
            for row in source_rows:
                lookup[(row["run_id"], str(row["detection_id"]))] = {
                    "uncertainty_status": "source_decode_failed"
                }
            continue
        for row in source_rows:
            key = (row["run_id"], str(row["detection_id"]))
            position = geometry.get(key)
            if position is None:
                lookup[key] = {"uncertainty_status": "measurement_geometry_unavailable"}
                continue
            estimate = _background_only_aperture_uncertainty(
                pixels, x=position[0], y=position[1], aperture_radius=position[2]
            )
            exposure = _finite(row.get("exposure_seconds"))
            rate = _finite(row.get("count_rate_adu_per_s"))
            if estimate is None or exposure is None or exposure <= 0 or rate is None or rate <= 0:
                lookup[key] = {"uncertainty_status": "background_uncertainty_unavailable"}
                continue
            saved_counts = rate * exposure
            if not math.isclose(
                estimate["aperture_counts_adu"], saved_counts,
                rel_tol=1e-8, abs_tol=1e-6,
            ):
                lookup[key] = {"uncertainty_status": "saved_aperture_not_reproduced"}
                continue
            rate_uncertainty = estimate["flux_uncertainty_adu"] / exposure
            magnitude_uncertainty = (
                2.5 / math.log(10.0) * rate_uncertainty / rate
            )
            lookup[key] = {
                "count_rate_uncertainty_adu_per_s": rate_uncertainty,
                "machine_magnitude_uncertainty": magnitude_uncertainty,
                "background_noise_adu": estimate["background_noise_adu"],
                "aperture_pixels": estimate["aperture_pixels"],
                "background_annulus_pixels": estimate["background_annulus_pixels"],
                "uncertainty_status": "available",
                "uncertainty_source": (
                    "checksum-verified native FITS; robust annulus MAD; "
                    "background-only aperture variance"
                ),
            }
    return lookup


def _normalise_utc(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith(" UTC"):
        text = text[:-4] + "+00:00"
    elif text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    result = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if "." in result:
        result = result[:-1].rstrip("0").rstrip(".") + "Z"
    return result


def _observation_time(product):
    if not product:
        return None
    try:
        values = json.loads(product)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    association = values.get("metadata_planet_association") or {}
    metadata = values.get("observation_time_metadata") or {}
    return _normalise_utc(association.get("time_utc") or metadata.get("time_utc"))


def _stellar_fit_from_product(product, channel):
    """Extract one complete saved channel fit without refitting any stars."""
    if not product:
        return None
    try:
        values = json.loads(product)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    fit = (values.get("extinction_by_channel") or {}).get(channel)
    if not isinstance(fit, dict):
        return None
    intercept = _finite(fit.get("intercept_mag"))
    extinction = _finite(fit.get("coefficient_mag_per_airmass"))
    rms = _finite(fit.get("rms_mag"))
    fitted_count = _finite(fit.get("fitted_count"))
    expected_relation = (
        f"{channel}_machine - catalogue_mag = intercept + k * airmass"
    )
    if (
        None in (intercept, extinction, rms, fitted_count)
        or rms < 0.0
        or fitted_count < 12
        or fit.get("relation") != expected_relation
    ):
        return None
    return {
        "stellar_intercept_mag": intercept,
        "stellar_extinction_mag_per_airmass": extinction,
        "stellar_fit_rms_mag": rms,
        "stellar_fit_count": int(fitted_count),
        "stellar_fit_status": str(fit.get("status", "")),
        "stellar_catalogue_passband": str(fit.get("catalogue_passband", "")),
    }


def _planet_altitude_lookup(product):
    """Index saved measured altitudes by finalized identity kind and source."""
    if not product:
        return {}
    try:
        values = json.loads(product)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    groups = [
        ("selected_planet_match", values.get("matches") or []),
        (
            "metadata_time_match",
            (values.get("metadata_planet_association") or {}).get("matches") or [],
        ),
    ]
    lookup = {}
    for identity_status, matches in groups:
        for match in matches:
            if not isinstance(match, dict):
                continue
            planet = str(match.get("planet", "")).casefold()
            detection_id = str(match.get("detection_id", ""))
            if planet and detection_id:
                lookup[(identity_status, planet, detection_id)] = _finite(
                    match.get("measured_altitude_deg")
                )
    return lookup


def _stellar_calibration_fields(
    stellar_fit, altitude_lookup, *, identity_status, planet, detection_id
):
    """Build audited same-run calibration fields for one finalized planet row."""
    empty = {
        "planet_measured_altitude_deg": None,
        "planet_airmass": None,
        "stellar_intercept_mag": None,
        "stellar_extinction_mag_per_airmass": None,
        "stellar_calibration_offset_mag": None,
        "stellar_fit_rms_mag": None,
        "stellar_fit_count": None,
        "stellar_fit_status": "",
        "stellar_catalogue_passband": "",
        "stellar_calibration_source": "",
    }
    altitude = altitude_lookup.get(
        (identity_status, str(planet).casefold(), str(detection_id))
    )
    empty["planet_measured_altitude_deg"] = altitude
    airmass = _kasten_young_airmass(altitude) if altitude is not None else None
    empty["planet_airmass"] = airmass
    if stellar_fit is None:
        return {**empty, "stellar_calibration_status": "stellar_fit_unavailable"}
    empty.update(stellar_fit)
    if altitude is None:
        return {**empty, "stellar_calibration_status": "planet_altitude_unavailable"}
    if airmass is None:
        return {**empty, "stellar_calibration_status": "planet_altitude_invalid"}
    empty.update({
        "stellar_calibration_offset_mag": (
            stellar_fit["stellar_intercept_mag"]
            + stellar_fit["stellar_extinction_mag_per_airmass"] * airmass
        ),
        "stellar_calibration_status": "available",
        "stellar_calibration_source": (
            "same-run photometry_summary.json channel fit evaluated at "
            "planet_epoch.json measured_altitude_deg"
        ),
    })
    return empty


def _quality(values, channel, exposure_seconds=None):
    seconds = _finite(exposure_seconds)
    if seconds is None:
        seconds = _finite(values.get("exposure_seconds"))
    rate = _finite(values.get(f"{channel}_count_rate_adu_per_s"))
    flux = _finite(values.get(f"{channel}_flux"))
    saturation_known = str(values.get("saturation_known", "")).casefold() == "true"
    saturated = str(values.get(f"{channel}_saturated", values.get("saturated", ""))).casefold()
    method = values.get(f"{channel}_measurement_method", "")
    if seconds is None or seconds <= 0:
        return rate, None, "missing_or_nonpositive_exposure"
    if not saturation_known:
        return rate, None, "saturation_unknown"
    if saturated != "false":
        return rate, None, f"{channel}_saturated"
    if method != "aperture":
        return rate, None, f"{channel}_measurement_not_aperture"
    if rate is None and flux is not None:
        rate = flux / seconds
    if rate is None or rate <= 0:
        return rate, None, f"nonpositive_or_nonfinite_{channel}_count_rate"
    return rate, -2.5 * math.log10(rate), ""


def _camera_identity(source_path):
    """Return a display camera label with an explicit path-based provenance."""
    path = str(source_path)
    lowered = path.casefold()
    if "apicam" in lowered:
        return "APICAM", "source path contains APICAM"
    if "mmto" in lowered:
        return "MMTO skycam", "source path contains MMTO"
    if "subaru_maunakea" in lowered:
        return "Subaru/Maunakea skycam", "source filename prefix subaru_maunakea"
    if "milkyway_gc" in lowered:
        return "Olympus E-M1 Mark II", "source filename family; camera model verified in retained EXIF"
    if any(token in lowered for token in ("fisheye18", "espenak")):
        return "Nikon D750 / Espenak", "source filename family; camera model verified in retained EXIF"
    marker = "/raw_allsky_samples/"
    if marker in lowered:
        tail = path[lowered.index(marker) + len(marker):]
        provider = tail.split("/", 1)[0].strip()
        if provider:
            return f"{provider} camera", "raw_allsky_samples provider path"
    return "Unidentified camera", "camera identity unavailable in saved database provenance"


def _positive_seconds(value):
    """Interpret a scalar or rational duration, rejecting units and invalid values."""
    if isinstance(value, (tuple, list)) and len(value) == 2:
        numerator = _finite(value[0])
        denominator = _finite(value[1])
        seconds = (numerator / denominator
                   if numerator is not None and denominator not in (None, 0) else None)
    elif isinstance(value, str):
        text = value.strip()
        match = re.fullmatch(
            r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))(?:\s*/\s*"
            r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)))?",
            text,
        )
        if not match:
            return None
        numerator = _finite(match.group(1))
        denominator = _finite(match.group(2)) if match.group(2) else 1.0
        seconds = (numerator / denominator
                   if numerator is not None and denominator not in (None, 0) else None)
    else:
        seconds = _finite(value)
    return seconds if seconds is not None and seconds > 0 else None


def _exposure_candidate(kind, location, key, value):
    seconds = _positive_seconds(value)
    return {
        "kind": kind,
        "location": location,
        "key": key,
        "raw_value": str(value),
        "seconds": seconds,
    }


def _raster_exposure_metadata(path):
    from PIL import ExifTags, Image

    candidates = []
    examined = []
    with Image.open(path) as image:
        exif = image.getexif()
        ifd_maps = [("IFD0", exif)]
        for ifd in ExifTags.IFD:
            try:
                values = exif.get_ifd(ifd)
            except (KeyError, TypeError, ValueError, SyntaxError):
                continue
            if values and hasattr(values, "items"):
                location = "ExifIFD" if ifd == ExifTags.IFD.Exif else ifd.name
                ifd_maps.append((location, values))
        seen_ifds = set()
        for location, values in ifd_maps:
            identity = (location, tuple(sorted(str(key) for key in values)))
            if identity in seen_ifds:
                continue
            seen_ifds.add(identity)
            for tag, value in values.items():
                name = ExifTags.TAGS.get(tag, str(tag))
                if name == "ExposureTime" or tag == 33434:
                    candidate = _exposure_candidate("exif", location, "ExposureTime", value)
                    examined.append(candidate)
                    if candidate["seconds"] is not None:
                        candidates.append(candidate)

        xmp = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
        if xmp:
            try:
                root = ET.fromstring(xmp)
            except (ET.ParseError, TypeError, ValueError):
                examined.append({
                    "kind": "xmp", "location": "XMP", "key": "parse_error",
                    "raw_value": "malformed XML", "seconds": None,
                })
            else:
                for element in root.iter():
                    for key, value in element.attrib.items():
                        if key.rsplit("}", 1)[-1].casefold() == "exposuretime":
                            candidate = _exposure_candidate(
                                "xmp", "XMP", "ExposureTime", value
                            )
                            examined.append(candidate)
                            if candidate["seconds"] is not None:
                                candidates.append(candidate)
                    if element.tag.rsplit("}", 1)[-1].casefold() == "exposuretime":
                        candidate = _exposure_candidate(
                            "xmp", "XMP", "ExposureTime", element.text or ""
                        )
                        examined.append(candidate)
                        if candidate["seconds"] is not None:
                            candidates.append(candidate)

        text_values = {}
        text_values.update(getattr(image, "text", {}) or {})
        for key, value in image.info.items():
            if isinstance(value, (str, int, float)):
                text_values.setdefault(key, value)
        accepted_text_keys = {
            "exposuretime", "exposureseconds", "exptime", "exposure",
            "integrationtime", "integrationseconds",
        }
        for key, value in text_values.items():
            normalised = re.sub(r"[^a-z0-9]", "", str(key).casefold())
            if normalised in accepted_text_keys:
                candidate = _exposure_candidate(
                    "raster_text", "raster_text", str(key), value
                )
                examined.append(candidate)
                if candidate["seconds"] is not None:
                    candidates.append(candidate)
    return candidates, examined


def _fits_exposure_metadata(path):
    from astropy.io import fits

    candidates = []
    examined = []
    direct_keys = {
        "EXPTIME", "EXPOSURE", "EXP_TIME", "EXPOSURETIME", "EXPOSURE_TIME",
        "ITIME", "INTTIME", "INTEGRAT", "INTEGRATION", "INTEGRATIONTIME",
        "INTEGRATION_TIME",
    }
    exposure_words = re.compile(
        r"\b(?:EXPOSURE|EXPTIME|EXP_TIME|INTEGRATION|INTEGRATION_TIME|"
        r"SHUTTER|DIT|NDIT|ITIME|INTTIME)\b",
        re.I,
    )
    with fits.open(path, memmap=False) as hdus:
        for index, hdu in enumerate(hdus):
            hdu_name = str(hdu.name or "PRIMARY")
            location = f"HDU{index}:{hdu_name}"
            for card in hdu.header.cards:
                key = str(card.keyword).strip()
                normalised = key.upper().removeprefix("HIERARCH ").strip()
                if normalised in direct_keys:
                    candidate = _exposure_candidate("fits", location, key, card.value)
                    candidate["comment"] = str(card.comment or "")
                    examined.append(candidate)
                    if candidate["seconds"] is not None:
                        candidates.append(candidate)
                elif exposure_words.search(key) or exposure_words.search(str(card.comment or "")):
                    examined.append({
                        "kind": "fits_context", "location": location, "key": key,
                        "raw_value": str(card.value), "seconds": None,
                        "comment": str(card.comment or ""),
                    })
    return candidates, examined


def _candidate_provenance(candidate):
    if candidate["kind"] == "fits":
        prefix = f"source_fits:{candidate['location']}:{candidate['key']}"
    elif candidate["kind"] == "exif":
        prefix = f"source_exif:{candidate['location']}:{candidate['key']}"
    elif candidate["kind"] == "xmp":
        prefix = f"source_xmp:{candidate['key']}"
    else:
        prefix = f"source_raster_text:{candidate['key']}"
    return prefix + " (SHA-256 verified)"


def _inspect_source_exposure(source_path, expected_sha256):
    """Search all supported header layers after binding the file to its saved hash."""
    path = Path(source_path)
    expected = str(expected_sha256 or "").casefold()
    answer = {
        "source_path": str(path), "source_sha256": expected,
        "source_present": path.is_file(), "checksum_status": "not_checked",
        "source_format": "", "status": "source_missing",
        "accepted_seconds": None, "accepted_source": "",
        "candidates": [], "examined_metadata": [],
    }
    if not path.is_file():
        return answer
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        answer.update(checksum_status="unavailable", status="source_checksum_unavailable")
        return answer
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        answer.update(checksum_status="mismatch", status="source_checksum_mismatch")
        return answer
    answer["checksum_status"] = "verified"

    suffixes = [suffix.casefold() for suffix in path.suffixes]
    if any(suffix in {".fits", ".fit", ".fts"} for suffix in suffixes):
        answer["source_format"] = "fits" + (".bz2" if suffixes[-1:] == [".bz2"] else "")
        candidates, examined = _fits_exposure_metadata(path)
    elif path.suffix.casefold() in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
        answer["source_format"] = path.suffix.casefold().lstrip(".")
        candidates, examined = _raster_exposure_metadata(path)
    else:
        answer.update(source_format=path.suffix.casefold().lstrip("."),
                      status="unsupported_source_format")
        return answer
    answer["candidates"] = candidates
    answer["examined_metadata"] = examined
    if not candidates:
        answer["status"] = "no_supported_exposure_metadata"
        return answer
    reference = candidates[0]["seconds"]
    if any(not math.isclose(candidate["seconds"], reference,
                            rel_tol=1e-9, abs_tol=1e-12)
           for candidate in candidates[1:]):
        answer["status"] = "conflicting_exposure_metadata"
        return answer
    answer.update(
        status="accepted", accepted_seconds=reference,
        accepted_source=_candidate_provenance(candidates[0]),
    )
    return answer


def _verified_source_exposure(source_path, expected_sha256):
    result = _inspect_source_exposure(source_path, expected_sha256)
    return result["accepted_seconds"], result["accepted_source"]


def _camera_marker_map(rows):
    labels = sorted({row["camera_label"] for row in rows})
    assigned = {}
    used = set()
    for label in labels:
        marker = PREFERRED_CAMERA_MARKERS.get(label)
        if marker is not None and marker not in used:
            assigned[label] = marker
            used.add(marker)
    available = [marker for marker in AVAILABLE_CAMERA_MARKERS if marker not in used]
    for label in labels:
        if label in assigned:
            continue
        if not available:
            raise ValueError("Too many camera identities for distinct plot markers")
        assigned[label] = available.pop(0)
    return assigned


def _build_figure(usable, camera_markers, planet_colours, *, channel):
    """Build a figure whose explanatory labels cannot cover the data axes."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    figure = plt.figure(figsize=(15.5, 7.5), constrained_layout=True)
    layout = figure.add_gridspec(
        2, 2, width_ratios=(6.0, 1.55), height_ratios=(1.0, 1.0)
    )
    axis = figure.add_subplot(layout[:, 0])
    planet_legend_axis = figure.add_subplot(layout[0, 1])
    camera_legend_axis = figure.add_subplot(layout[1, 1])
    planet_legend_axis.set_axis_off()
    camera_legend_axis.set_axis_off()

    groups = sorted({(row["planet"], row["camera_label"]) for row in usable})
    for planet, camera in groups:
        points = [row for row in usable
                  if row["planet"] == planet and row["camera_label"] == camera]
        points.sort(key=lambda row: row["observation_time_utc"])
        times = [datetime.fromisoformat(row["observation_time_utc"].replace("Z", "+00:00"))
                 for row in points]
        magnitudes = [row["machine_magnitude"] for row in points]
        if len(points) > 1:
            axis.plot(
                times,
                magnitudes,
                color=planet_colours[planet],
                linewidth=1.0,
                alpha=0.45,
                zorder=2,
            )
        axis.scatter(
            times,
            magnitudes,
            s=34,
            color=planet_colours[planet],
            marker=camera_markers[camera],
            edgecolor="black",
            linewidth=0.35,
            alpha=0.85,
            zorder=3,
        )
    axis.set_title("Detected planets: instrumental magnitude versus observation time")
    axis.set_xlabel("Observation time (UTC; metadata revealed after the solve)")
    axis.set_ylabel(f"{channel} machine magnitude = −2.5 log₁₀(count rate [ADU/s])")
    axis.grid(True, alpha=0.25, linewidth=0.7)
    if usable:
        axis.invert_yaxis()
        planet_handles = [
            Line2D([], [], linestyle="none", marker="o", markersize=7,
                   markerfacecolor=colour, markeredgecolor="black",
                   label=f"{planet} (n={sum(row['planet'] == planet for row in usable)})")
            for planet, colour in planet_colours.items()
        ]
        camera_handles = [
            Line2D([], [], linestyle="none", marker=marker, markersize=7,
                   markerfacecolor="#777777", markeredgecolor="black", label=camera)
            for camera, marker in camera_markers.items()
        ]
        planet_legend_axis.legend(
            handles=planet_handles, title="Planet (colour)", loc="upper left", frameon=True
        )
        camera_legend_axis.legend(
            handles=camera_handles, title="Camera (symbol)", loc="upper left", frameon=True
        )
        locator = mdates.AutoDateLocator(minticks=4, maxticks=10)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, tz=timezone.utc))
    else:
        axis.text(0.5, 0.5, "No unsaturated metadata-associated planet photometry",
                  ha="center", va="center", transform=axis.transAxes)
    camera_legend_axis.text(
        0.0,
        0.0,
        "Colour = planet; symbol = camera.\n"
        "Only complete finalized-identity count rates plotted.",
        transform=camera_legend_axis.transAxes,
        fontsize=8,
        color="#444444",
        va="bottom",
        wrap=True,
    )
    return figure, axis


def _build_distance_corrected_figure(
    usable,
    camera_markers,
    planet_colours,
    *,
    channel,
    magnitude_field="distance_corrected_magnitude",
    uncertainty_field="machine_magnitude_uncertainty",
    title="Detected planets: distance-corrected instrumental magnitude versus time",
    ylabel=None,
    empty_message="No complete distance-corrected planet photometry",
    explanation=None,
):
    """Build the distance-normalized plot with empirical 1-sigma error bars."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    figure = plt.figure(figsize=(15.5, 7.5), constrained_layout=True)
    layout = figure.add_gridspec(
        2, 2, width_ratios=(6.0, 1.55), height_ratios=(1.0, 1.0)
    )
    axis = figure.add_subplot(layout[:, 0])
    planet_legend_axis = figure.add_subplot(layout[0, 1])
    camera_legend_axis = figure.add_subplot(layout[1, 1])
    planet_legend_axis.set_axis_off()
    camera_legend_axis.set_axis_off()

    groups = sorted({(row["planet"], row["camera_label"]) for row in usable})
    for planet, camera in groups:
        points = [
            row for row in usable
            if row["planet"] == planet and row["camera_label"] == camera
        ]
        points.sort(key=lambda row: row["observation_time_utc"])
        times = [
            datetime.fromisoformat(row["observation_time_utc"].replace("Z", "+00:00"))
            for row in points
        ]
        magnitudes = [row[magnitude_field] for row in points]
        uncertainties = [row[uncertainty_field] for row in points]
        if len(points) > 1:
            axis.plot(
                times, magnitudes, color=planet_colours[planet],
                linewidth=1.0, alpha=0.45, zorder=2,
            )
        axis.errorbar(
            times,
            magnitudes,
            yerr=uncertainties,
            fmt="none",
            ecolor=planet_colours[planet],
            elinewidth=0.9,
            alpha=0.8,
            capsize=0,
            zorder=2.5,
        )
        axis.scatter(
            times,
            magnitudes,
            s=34,
            color=planet_colours[planet],
            marker=camera_markers[camera],
            edgecolor="black",
            linewidth=0.35,
            alpha=0.9,
            zorder=3,
        )
    axis.set_title(title)
    axis.set_xlabel("Observation time (UTC; metadata revealed after the solve)")
    axis.set_ylabel(ylabel or (
        f"{channel} machine magnitude corrected to r☉₋ₚ = r⊕₋ₚ = 1 AU"
    ))
    axis.grid(True, alpha=0.25, linewidth=0.7)
    if usable:
        axis.invert_yaxis()
        planet_handles = [
            Line2D(
                [], [], linestyle="-", linewidth=1.0, marker="o", markersize=7,
                color=colour, markerfacecolor=colour, markeredgecolor="black",
                label=f"{planet} (n={sum(row['planet'] == planet for row in usable)})",
            )
            for planet, colour in planet_colours.items()
        ]
        camera_handles = [
            Line2D(
                [], [], linestyle="none", marker=marker, markersize=7,
                markerfacecolor="#777777", markeredgecolor="black", label=camera,
            )
            for camera, marker in camera_markers.items()
        ]
        planet_legend_axis.legend(
            handles=planet_handles, title="Planet (colour)",
            loc="upper left", frameon=True,
        )
        camera_legend_axis.legend(
            handles=camera_handles, title="Camera (symbol)",
            loc="upper left", frameon=True,
        )
        locator = mdates.AutoDateLocator(minticks=4, maxticks=10)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(
            mdates.ConciseDateFormatter(locator, tz=timezone.utc)
        )
    else:
        axis.text(
            0.5, 0.5, empty_message,
            ha="center", va="center", transform=axis.transAxes,
        )
    camera_legend_axis.text(
        0.0,
        0.0,
        explanation or (
            "Distance correction: m − 5 log₁₀(r☉₋ₚ r⊕₋ₚ), distances in AU.\n"
            "Bars: empirical background-only 1σ; gain/source noise and systematics excluded.\n"
            "No correction for phase, atmosphere, passband, clouds, or camera response."
        ),
        transform=camera_legend_axis.transAxes,
        fontsize=7.5,
        color="#444444",
        va="bottom",
        wrap=True,
    )
    return figure, axis


def _build_stellar_calibrated_distance_figure(
    usable, camera_markers, planet_colours, *, channel
):
    """Build the star-calibrated and distance-normalized planet plot."""
    return _build_distance_corrected_figure(
        usable,
        camera_markers,
        planet_colours,
        channel=channel,
        magnitude_field="stellar_calibrated_distance_magnitude",
        uncertainty_field="total_magnitude_uncertainty",
        title=(
            "Detected planets: stellar-calibrated, distance-corrected "
            "magnitude versus time"
        ),
        ylabel=(
            f"{channel} stellar-calibrated magnitude at "
            "r☉₋ₚ = r⊕₋ₚ = 1 AU"
        ),
        empty_message="No complete stellar-calibrated planet photometry",
        explanation=(
            "Stellar calibration: m − (intercept + k × airmass), fitted per image/channel.\n"
            "Distance correction: −5 log₁₀(r☉₋ₚ r⊕₋ₚ), distances in AU.\n"
            "Bars: aperture uncertainty ⊕ stellar-fit RMS; passband/phase systematics remain."
        ),
    )


def load_planet_measurements(database, channel="G"):
    """Return finalized planet detections from the latest successful image runs."""
    if channel not in {"R", "G", "B"}:
        raise ValueError("channel must be R, G or B")
    audit = Counter()
    rows = []
    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        runs = connection.execute(
            """SELECT run_id,recorded_at_utc,source_path,source_sha256,
                      catalogue_sha256,exit_code
               FROM runs ORDER BY recorded_at_utc,run_id"""
        ).fetchall()
        latest = {}
        for run in runs:
            audit["database_runs"] += 1
            if run[5] != 0:
                audit["failed_runs_omitted"] += 1
                continue
            audit["successful_runs"] += 1
            key = (run[3] or run[2], run[4] or "")
            if key in latest:
                audit["duplicate_successful_runs_omitted"] += 1
            latest[key] = run
        audit["selected_latest_successful_runs"] = len(latest)

        for (
            run_id,
            recorded,
            source_path,
            source_sha256,
            catalogue_sha256,
            _,
        ) in latest.values():
            camera_label, camera_provenance = _camera_identity(source_path)
            recovered_exposure = None
            recovered_exposure_checked = False
            saved = connection.execute(
                "SELECT content FROM products WHERE run_id=? AND product='planet_epoch.json'",
                (run_id,),
            ).fetchone()
            observation_time = _observation_time(saved[0] if saved else None)
            altitude_lookup = _planet_altitude_lookup(saved[0] if saved else None)
            saved_photometry = connection.execute(
                "SELECT content FROM products "
                "WHERE run_id=? AND product='photometry_summary.json'",
                (run_id,),
            ).fetchone()
            stellar_fit = _stellar_fit_from_product(
                saved_photometry[0] if saved_photometry else None, channel
            )
            query = connection.execute(
                """SELECT row_number,detection_id,values_json FROM measurements
                   WHERE run_id=? AND product='identified_source_photometry.csv'
                   ORDER BY row_number""",
                (run_id,),
            )
            for row_number, detection_id, payload in query:
                values = json.loads(payload)
                identity_type = values.get("identity_type", "")
                identity_status = values.get("identity_status", "")
                if identity_type not in PLANET_TYPES:
                    audit["non_planet_identity_rows_omitted"] += 1
                    continue
                if identity_status not in DETECTION_STATUSES:
                    audit["non_detection_identity_rows_omitted"] += 1
                    continue
                audit["detected_planet_rows"] += 1
                audit[f"{identity_status}_rows"] += 1
                planet = values.get("identity_name", "")
                finalized_detection_id = values.get(
                    "detection_id", detection_id or ""
                )
                calibration_fields = _stellar_calibration_fields(
                    stellar_fit,
                    altitude_lookup,
                    identity_status=identity_status,
                    planet=planet,
                    detection_id=finalized_detection_id,
                )
                audit[
                    "stellar_calibration_"
                    + calibration_fields["stellar_calibration_status"]
                    + "_rows"
                ] += 1
                exposure_seconds = _finite(values.get("exposure_seconds"))
                exposure_source = values.get("exposure_source", "")
                if exposure_seconds is None or exposure_seconds <= 0:
                    if not recovered_exposure_checked:
                        recovered_exposure = _verified_source_exposure(
                            source_path, source_sha256
                        )
                        recovered_exposure_checked = True
                        if recovered_exposure[0] is not None:
                            audit["source_metadata_exposure_images_recovered"] += 1
                    if recovered_exposure and recovered_exposure[0] is not None:
                        exposure_seconds, exposure_source = recovered_exposure
                        audit["source_metadata_exposure_rows_recovered"] += 1
                rate, magnitude, reason = _quality(
                    values, channel, exposure_seconds=exposure_seconds
                )
                if observation_time is None:
                    reason = "missing_observation_time_utc"
                    magnitude = None
                usable = not reason
                audit["usable_photometry_rows" if usable else "unusable_photometry_rows"] += 1
                if reason:
                    audit[f"excluded_{reason}"] += 1
                rows.append(
                    {
                        "run_id": run_id,
                        "recorded_at_utc": recorded,
                        "source_path": source_path,
                        "source_sha256": source_sha256 or "",
                        "catalogue_sha256": catalogue_sha256 or "",
                        "observation_time_utc": observation_time or "",
                        "camera_label": camera_label,
                        "camera_provenance": camera_provenance,
                        "planet_type": identity_type,
                        "planet": planet,
                        "identity_status": identity_status,
                        "candidate_rank": values.get("candidate_rank", ""),
                        "detection_id": finalized_detection_id,
                        "source_class": values.get("source_class", ""),
                        "channel": channel,
                        "exposure_seconds": exposure_seconds,
                        "exposure_source": exposure_source,
                        "count_rate_adu_per_s": rate,
                        "machine_magnitude": magnitude,
                        **calibration_fields,
                        "photometry_usable": usable,
                        "exclusion_reason": reason,
                        "saturation_known": values.get("saturation_known", ""),
                        "channel_saturated": values.get(f"{channel}_saturated", ""),
                        "measurement_method": values.get(f"{channel}_measurement_method", ""),
                        "row_number": row_number,
                    }
                )
        connection.rollback()
    rows.sort(key=lambda row: (row["observation_time_utc"], row["planet"], str(row["detection_id"])))
    audit["planet_counts"] = dict(Counter(row["planet"] for row in rows))
    audit["usable_planet_counts"] = dict(
        Counter(row["planet"] for row in rows if row["photometry_usable"])
    )
    return rows, dict(audit)


def _source_exposure_audit_rows(rows):
    grouped = {}
    for row in rows:
        key = (row["source_path"], row["source_sha256"])
        grouped.setdefault(key, []).append(row)
    records = []
    for (source_path, source_sha256), source_rows in sorted(grouped.items()):
        result = _inspect_source_exposure(source_path, source_sha256)
        database_seconds = sorted({
            float(row["exposure_seconds"])
            for row in source_rows
            if _finite(row.get("exposure_seconds")) is not None
            and not str(row.get("exposure_source", "")).startswith("source_")
        })
        database_sources = sorted({
            str(row.get("exposure_source", ""))
            for row in source_rows
            if row.get("exposure_source")
            and not str(row.get("exposure_source", "")).startswith("source_")
        })
        records.append({
            "source_path": source_path,
            "source_sha256": source_sha256,
            "source_present": result["source_present"],
            "checksum_status": result["checksum_status"],
            "source_format": result["source_format"],
            "search_status": result["status"],
            "accepted_source_seconds": result["accepted_seconds"],
            "accepted_source_provenance": result["accepted_source"],
            "database_exposure_seconds": json.dumps(database_seconds),
            "database_exposure_sources": json.dumps(database_sources),
            "candidates_json": json.dumps(result["candidates"], sort_keys=True),
            "examined_metadata_json": json.dumps(
                result["examined_metadata"], sort_keys=True
            ),
        })
    return records


def write_outputs(
    rows,
    audit,
    output,
    *,
    database,
    channel="G",
    skip_earliest_observations=0,
):
    """Write the full audit table and a single planet-coloured magnitude figure."""
    if skip_earliest_observations < 0:
        raise ValueError("skip_earliest_observations must be nonnegative")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    complete = [row for row in rows if row["photometry_usable"]]
    observation_order = list(dict.fromkeys(
        row["source_sha256"] or row["source_path"] for row in complete
    ))
    omitted_observations = set(observation_order[:skip_earliest_observations])
    usable = [
        row for row in complete
        if (row["source_sha256"] or row["source_path"]) not in omitted_observations
    ]
    camera_markers = _camera_marker_map(usable)
    planet_colours = {
        planet: PLANET_COLOURS[planet]
        for planet in sorted({row["planet"] for row in usable})
    }
    with (output / "planet_measurements.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(usable)
    with (output / "planet_detection_audit.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    exposure_audit_rows = _source_exposure_audit_rows(rows)
    with (output / "exposure_metadata_audit.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=EXPOSURE_AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(exposure_audit_rows)

    plotted_by_camera = {}
    for camera in sorted({row["camera_label"] for row in usable}):
        camera_rows = [row for row in usable if row["camera_label"] == camera]
        plotted_by_camera[camera] = {
            "measurements": len(camera_rows),
            "unique_source_images": len({
                row["source_sha256"] or row["source_path"] for row in camera_rows
            }),
        }

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "database": str(Path(database).resolve()),
        "channel": channel,
        "machine_magnitude_definition": f"-2.5 log10({channel} count rate [ADU/s])",
        "identity_selection": (
            "identified_source_photometry.csv rows with a major/minor planet identity "
            "and a finalized identity_status of metadata_time_match or "
            "selected_planet_match; generic planet_candidate alternatives are excluded"
        ),
        "observation_time_source": "planet_epoch.json metadata association UTC",
        "exposure_policy": (
            "saved positive exposure_seconds, with a read-only checksum-verified source "
            "search across every FITS HDU, EXIF IFD, XMP packet and supported raster "
            "text field; conflicting values are rejected"
        ),
        "exposure_metadata_audit_csv": (
            "exposure_metadata_audit.csv records every source-level search, candidate, "
            "checksum result and retained database exposure"
        ),
        "deduplication": "newest successful run per source image SHA-256 (path fallback)",
        "saturation_policy": (
            "channel saturation must be known false and the saved measurement method "
            "must be aperture; excluded detections remain only in planet_detection_audit.csv"
        ),
        "plotted_data_csv": "planet_measurements.csv contains complete plotted rows only",
        "plot_selection": {
            "skip_earliest_observations": skip_earliest_observations,
            "observations_omitted": len(omitted_observations),
            "measurements_omitted": len(complete) - len(usable),
            "earliest_retained_time_utc": (
                usable[0]["observation_time_utc"] if usable else None
            ),
        },
        "plotted_counts": {
            "measurements": len(usable),
            "unique_source_images": len({
                row["source_sha256"] or row["source_path"] for row in usable
            }),
            "by_camera": plotted_by_camera,
            "by_identity_status": dict(Counter(
                row["identity_status"] for row in usable
            )),
        },
        "visual_encoding": {
            "colour": "planet",
            "marker": "camera",
            "planet_colours": planet_colours,
            "camera_markers": camera_markers,
        },
        "audit": audit,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    fig, _ = _build_figure(
        usable, camera_markers, planet_colours, channel=channel
    )
    import matplotlib.pyplot as plt
    fig.savefig(output / "planet_machine_magnitude_vs_time.png", dpi=180)
    fig.savefig(output / "planet_machine_magnitude_vs_time.pdf")
    plt.close(fig)
    return summary


def write_distance_corrected_outputs(
    rows,
    audit,
    output,
    *,
    database,
    channel="G",
    skip_earliest_observations=0,
    distance_lookup=None,
    uncertainty_lookup=None,
):
    """Write only complete distance-normalized photometry and its provenance."""
    if skip_earliest_observations < 0:
        raise ValueError("skip_earliest_observations must be nonnegative")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    complete = [row for row in rows if row["photometry_usable"]]
    observation_order = list(dict.fromkeys(
        row["source_sha256"] or row["source_path"] for row in complete
    ))
    omitted_observations = set(observation_order[:skip_earliest_observations])
    selected = [
        row for row in complete
        if (row["source_sha256"] or row["source_path"]) not in omitted_observations
    ]
    if distance_lookup is None:
        distance_lookup = _horizons_distance_lookup(selected)
    if uncertainty_lookup is None:
        uncertainty_lookup = _photometric_uncertainty_lookup(
            selected, database, channel=channel
        )

    corrected = []
    incomplete = []
    for original in selected:
        row = dict(original)
        distance = distance_lookup.get(
            (row["planet"], row["observation_time_utc"])
        )
        uncertainty = uncertainty_lookup.get(
            (row["run_id"], str(row["detection_id"])), {}
        )
        row.update(uncertainty)
        if distance is None:
            row["corrected_exclusion_reason"] = "distance_ephemeris_unavailable"
            incomplete.append(row)
            continue
        row.update(distance)
        corrected_magnitude = _distance_corrected_magnitude(
            row["machine_magnitude"],
            row["sun_planet_distance_au"],
            row["earth_planet_distance_au"],
        )
        magnitude_uncertainty = _finite(row.get("machine_magnitude_uncertainty"))
        if corrected_magnitude is None or magnitude_uncertainty is None or magnitude_uncertainty <= 0:
            row["corrected_exclusion_reason"] = (
                row.get("uncertainty_status") or "photometric_uncertainty_unavailable"
            )
            incomplete.append(row)
            continue
        row["distance_correction_mag"] = (
            float(row["machine_magnitude"]) - corrected_magnitude
        )
        row["distance_corrected_magnitude"] = corrected_magnitude
        corrected.append(row)

    with (output / "planet_distance_corrected_measurements.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=DISTANCE_CORRECTED_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(corrected)

    ephemeris_records = []
    for (planet, time_utc), record in sorted(distance_lookup.items()):
        ephemeris_records.append({
            "planet": planet,
            "observation_time_utc": time_utc,
            **record,
        })
    ephemeris_fields = [
        "planet", "observation_time_utc", "jd_utc",
        "sun_planet_distance_au", "earth_planet_distance_au",
        "distance_ephemeris_source",
    ]
    with (output / "planet_distance_ephemeris.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=ephemeris_fields, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(ephemeris_records)

    camera_markers = _camera_marker_map(corrected)
    planet_colours = {
        planet: PLANET_COLOURS[planet]
        for planet in sorted({row["planet"] for row in corrected})
    }
    plotted_by_camera = {}
    for camera in sorted({row["camera_label"] for row in corrected}):
        camera_rows = [row for row in corrected if row["camera_label"] == camera]
        plotted_by_camera[camera] = {
            "measurements": len(camera_rows),
            "unique_source_images": len({
                row["source_sha256"] or row["source_path"] for row in camera_rows
            }),
        }
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "database": str(Path(database).resolve()),
        "channel": channel,
        "quantity": "distance-corrected instrumental magnitude",
        "formula": (
            "m_corrected = -2.5 log10(count_rate_ADU_per_s) "
            "- 5 log10(sun_planet_distance_AU * earth_planet_distance_AU)"
        ),
        "normalization": "Sun-planet and Earth-planet distances both normalized to 1 AU",
        "distance_ephemeris": (
            "NASA/JPL Horizons API observer-table quantities 19 and 20 at exact UTC dates; "
            "Earth geocenter"
        ),
        "uncertainty": (
            "Empirical 1-sigma background-only aperture uncertainty from the "
            "checksum-verified native FITS plane and the original aperture geometry. "
            "Camera gain/source shot noise and systematic errors are not included."
        ),
        "uncorrected_effects": [
            "planetary phase", "atmospheric extinction", "clouds",
            "camera passband and response", "flat-field and calibration systematics",
        ],
        "plot_selection": {
            "skip_earliest_observations": skip_earliest_observations,
            "observations_omitted": len(omitted_observations),
            "measurements_omitted": len(complete) - len(selected),
            "earliest_retained_time_utc": (
                corrected[0]["observation_time_utc"] if corrected else None
            ),
        },
        "plotted_counts": {
            "measurements": len(corrected),
            "unique_source_images": len({
                row["source_sha256"] or row["source_path"] for row in corrected
            }),
            "by_planet": dict(Counter(row["planet"] for row in corrected)),
            "by_camera": plotted_by_camera,
        },
        "excluded_incomplete_corrected_rows": len(incomplete),
        "excluded_corrected_reasons": dict(Counter(
            row.get("corrected_exclusion_reason", "unspecified") for row in incomplete
        )),
        "source_detection_audit": audit,
    }
    (output / "distance_corrected_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    figure, _ = _build_distance_corrected_figure(
        corrected, camera_markers, planet_colours, channel=channel
    )
    import matplotlib.pyplot as plt
    figure.savefig(
        output / "planet_distance_corrected_magnitude_vs_time.png", dpi=180
    )
    figure.savefig(output / "planet_distance_corrected_magnitude_vs_time.pdf")
    plt.close(figure)
    return summary


def write_stellar_calibrated_distance_outputs(
    rows,
    audit,
    output,
    *,
    database,
    channel="G",
    skip_earliest_observations=0,
    distance_lookup=None,
    uncertainty_lookup=None,
):
    """Write complete same-run stellar-calibrated, distance-normalized data."""
    if skip_earliest_observations < 0:
        raise ValueError("skip_earliest_observations must be nonnegative")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    complete = [row for row in rows if row["photometry_usable"]]
    observation_order = list(dict.fromkeys(
        row["source_sha256"] or row["source_path"] for row in complete
    ))
    omitted_observations = set(observation_order[:skip_earliest_observations])
    selected = [
        row for row in complete
        if (row["source_sha256"] or row["source_path"])
        not in omitted_observations
    ]
    if distance_lookup is None:
        distance_lookup = _horizons_distance_lookup(selected)
    if uncertainty_lookup is None:
        uncertainty_lookup = _photometric_uncertainty_lookup(
            selected, database, channel=channel
        )

    calibrated = []
    incomplete = []
    for original in selected:
        row = dict(original)
        calibration_status = row.get("stellar_calibration_status")
        if calibration_status != "available":
            row["calibrated_exclusion_reason"] = (
                calibration_status or "stellar_calibration_unavailable"
            )
            incomplete.append(row)
            continue
        distance = distance_lookup.get(
            (row["planet"], row["observation_time_utc"])
        )
        if distance is None:
            row["calibrated_exclusion_reason"] = "distance_ephemeris_unavailable"
            incomplete.append(row)
            continue
        row.update(distance)
        uncertainty = uncertainty_lookup.get(
            (row["run_id"], str(row["detection_id"])), {}
        )
        row.update(uncertainty)
        measurement_uncertainty = _finite(
            row.get("machine_magnitude_uncertainty")
        )
        stellar_uncertainty = _finite(row.get("stellar_fit_rms_mag"))
        if (
            measurement_uncertainty is None
            or measurement_uncertainty <= 0.0
            or stellar_uncertainty is None
            or stellar_uncertainty < 0.0
        ):
            row["calibrated_exclusion_reason"] = (
                row.get("uncertainty_status")
                or "stellar_or_measurement_uncertainty_unavailable"
            )
            incomplete.append(row)
            continue
        corrected = _stellar_calibrated_distance_magnitude(
            row["machine_magnitude"],
            row["stellar_intercept_mag"],
            row["stellar_extinction_mag_per_airmass"],
            row["planet_measured_altitude_deg"],
            row["sun_planet_distance_au"],
            row["earth_planet_distance_au"],
        )
        offset = _finite(row.get("stellar_calibration_offset_mag"))
        if corrected is None or offset is None:
            row["calibrated_exclusion_reason"] = "calibration_calculation_failed"
            incomplete.append(row)
            continue
        row["stellar_calibrated_magnitude"] = (
            float(row["machine_magnitude"]) - offset
        )
        row["distance_corrected_magnitude"] = _distance_corrected_magnitude(
            row["machine_magnitude"],
            row["sun_planet_distance_au"],
            row["earth_planet_distance_au"],
        )
        row["stellar_calibrated_distance_magnitude"] = corrected
        row["distance_correction_mag"] = (
            row["stellar_calibrated_magnitude"] - corrected
        )
        row["stellar_fit_uncertainty_mag"] = stellar_uncertainty
        row["total_magnitude_uncertainty"] = math.hypot(
            measurement_uncertainty, stellar_uncertainty
        )
        calibrated.append(row)

    with (output / "planet_stellar_calibrated_distance_measurements.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=STELLAR_CALIBRATED_DISTANCE_FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(calibrated)

    camera_markers = _camera_marker_map(calibrated)
    planet_colours = {
        planet: PLANET_COLOURS[planet]
        for planet in sorted({row["planet"] for row in calibrated})
    }
    plotted_by_camera = {}
    for camera in sorted({row["camera_label"] for row in calibrated}):
        camera_rows = [
            row for row in calibrated if row["camera_label"] == camera
        ]
        plotted_by_camera[camera] = {
            "measurements": len(camera_rows),
            "unique_source_images": len({
                row["source_sha256"] or row["source_path"]
                for row in camera_rows
            }),
        }
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "database": str(Path(database).resolve()),
        "channel": channel,
        "quantity": "stellar-calibrated distance-corrected magnitude",
        "formula": (
            "m_calibrated_1_1 = -2.5 log10(count_rate_ADU_per_s) "
            "- (stellar_intercept + stellar_extinction * planet_airmass) "
            "- 5 log10(sun_planet_distance_AU * earth_planet_distance_AU)"
        ),
        "stellar_calibration": (
            "Same-run, same-channel saved stellar relation evaluated at the "
            "planet's measured altitude; no cross-camera zero point is assumed."
        ),
        "catalogue_passband_limitation": (
            "The stellar catalogue magnitude is used for every native channel; "
            "planet colour and camera-passband transformations are not fitted."
        ),
        "uncertainty": (
            "Quadrature sum of empirical background-only aperture uncertainty "
            "and the same-image stellar regression RMS. The RMS represents the "
            "calibration scatter for an object of unknown colour, not a formal "
            "zero-point standard error."
        ),
        "uncorrected_effects": [
            "planetary phase and rotation",
            "planet/camera passband colour term",
            "unmodelled flat-field, clouds, and detector non-linearity",
        ],
        "plot_selection": {
            "skip_earliest_observations": skip_earliest_observations,
            "observations_omitted": len(omitted_observations),
            "measurements_omitted": len(complete) - len(selected),
            "earliest_retained_time_utc": (
                calibrated[0]["observation_time_utc"] if calibrated else None
            ),
        },
        "plotted_counts": {
            "measurements": len(calibrated),
            "unique_source_images": len({
                row["source_sha256"] or row["source_path"]
                for row in calibrated
            }),
            "by_planet": dict(Counter(row["planet"] for row in calibrated)),
            "by_camera": plotted_by_camera,
        },
        "excluded_incomplete_calibrated_rows": len(incomplete),
        "excluded_calibrated_reasons": dict(Counter(
            row.get("calibrated_exclusion_reason", "unspecified")
            for row in incomplete
        )),
        "source_detection_audit": audit,
    }
    (output / "stellar_calibrated_distance_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    figure, _ = _build_stellar_calibrated_distance_figure(
        calibrated, camera_markers, planet_colours, channel=channel
    )
    import matplotlib.pyplot as plt
    figure.savefig(
        output / "planet_stellar_calibrated_distance_magnitude_vs_time.png",
        dpi=180,
    )
    figure.savefig(
        output / "planet_stellar_calibrated_distance_magnitude_vs_time.pdf"
    )
    plt.close(figure)
    return summary


def _build_extinction_corrected_distance_figure(
    usable, camera_markers, planet_colours, *, channel
):
    """Build the extinction-corrected and distance-normalized planet plot."""
    return _build_distance_corrected_figure(
        usable,
        camera_markers,
        planet_colours,
        channel=channel,
        magnitude_field="extinction_corrected_distance_magnitude",
        uncertainty_field="total_magnitude_uncertainty",
        title=(
            "Detected planets: extinction-corrected, "
            "distance-corrected magnitude versus time"
        ),
        ylabel=(
            f"{channel} extinction-corrected magnitude at "
            "r☉₋ₚ = r⊕₋ₚ = 1 AU"
        ),
        empty_message="No complete extinction-corrected planet photometry",
        explanation=(
            "Extinction correction: m − Z_fixed − k_night × planet airmass.\n"
            "Distance correction is then −5 log₁₀(r☉₋ₚ r⊕₋ₚ), distances in AU.\n"
            "Bars combine aperture, fixed-Z, and nightly k-stability components."
        ),
    )


def write_extinction_corrected_distance_outputs(
    rows,
    audit,
    output,
    *,
    database,
    nightly_calibration,
    channel="G",
    skip_earliest_observations=0,
    distance_lookup=None,
    uncertainty_lookup=None,
):
    """Apply only the explicit nightly extinction sidecar, then distances."""
    if skip_earliest_observations < 0:
        raise ValueError("skip_earliest_observations must be nonnegative")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    calibrations = load_nightly_image_calibrations(nightly_calibration)
    complete = [row for row in rows if row["photometry_usable"]]
    observation_order = list(dict.fromkeys(
        row["source_sha256"] or row["source_path"] for row in complete
    ))
    omitted_observations = set(observation_order[:skip_earliest_observations])
    selected = [
        row for row in complete
        if (row["source_sha256"] or row["source_path"])
        not in omitted_observations
    ]
    audit_candidates = [
        row for row in rows
        if (row["source_sha256"] or row["source_path"])
        not in omitted_observations
    ]
    if distance_lookup is None:
        distance_lookup = _horizons_distance_lookup(selected)
    if uncertainty_lookup is None:
        uncertainty_lookup = _photometric_uncertainty_lookup(
            selected, database, channel=channel
        )

    calibrated = []
    calibration_audit = []
    for original in audit_candidates:
        row = dict(original)
        row.update({
            "nightly_extinction_night": None,
            "nightly_extinction_mag_per_airmass": None,
            "nightly_extinction_scaled_mad": None,
            "nightly_zero_point_mag": None,
            "nightly_zero_point_uncertainty_mag": None,
            "extinction_corrected_magnitude": None,
            "extinction_corrected_distance_magnitude": None,
            "extinction_correction_status": "",
            "extinction_correction_source": str(
                Path(nightly_calibration).expanduser().resolve()
            ),
            "nightly_extinction_uncertainty_mag": None,
            "total_magnitude_uncertainty": None,
            "extinction_correction_exclusion_reason": "",
        })
        if row.get("identity_status") != "metadata_time_match":
            row["extinction_correction_status"] = (
                "blind_epoch_identity_not_observation_time"
            )
            row["extinction_correction_exclusion_reason"] = (
                "blind_epoch_identity_not_observation_time"
            )
            calibration_audit.append(row)
            continue
        night = _mmto_observing_night(row.get("observation_time_utc"))
        key = (
            row.get("source_sha256", ""),
            row.get("catalogue_sha256", ""),
            night or "",
            channel,
        )
        calibration = calibrations.get(key)
        if calibration is None:
            row["extinction_correction_status"] = "missing_sidecar_match"
            row["extinction_correction_exclusion_reason"] = "missing_sidecar_match"
            calibration_audit.append(row)
            continue
        identity_time = _normalise_utc(
            row.get("metadata_association_time_utc")
            or row.get("observation_time_utc")
        )
        calibration_time = calibration["observed_utc"]
        if identity_time is None or abs(
            (
                datetime.fromisoformat(identity_time.replace("Z", "+00:00"))
                - datetime.fromisoformat(
                    calibration_time.replace("Z", "+00:00")
                )
            ).total_seconds()
        ) > 60.0:
            row["extinction_correction_status"] = (
                "identity_time_disagrees_with_manifest_utc"
            )
            row["extinction_correction_exclusion_reason"] = (
                "identity_time_disagrees_with_manifest_utc"
            )
            calibration_audit.append(row)
            continue
        row["observation_time_utc"] = calibration_time
        if not row.get("photometry_usable"):
            reason = row.get("exclusion_reason") or "source_photometry_unusable"
            row["extinction_correction_status"] = "source_photometry_unusable"
            row["extinction_correction_exclusion_reason"] = reason
            calibration_audit.append(row)
            continue
        airmass = _finite(row.get("planet_airmass"))
        if airmass is None or airmass <= 0.0:
            row["extinction_correction_status"] = "planet_airmass_unavailable"
            row["extinction_correction_exclusion_reason"] = "planet_airmass_unavailable"
            calibration_audit.append(row)
            continue
        extinction = calibration["extinction_mag_per_airmass"]
        scaled_mad = calibration["extinction_scaled_mad"]
        zero_point = calibration["zero_point_magnitude"]
        zero_uncertainty = calibration["zero_point_uncertainty_magnitude"]
        extinction_corrected_magnitude = (
            float(row["machine_magnitude"])
            - zero_point
            - extinction * airmass
        )
        row.update({
            "nightly_extinction_night": night,
            "nightly_extinction_mag_per_airmass": extinction,
            "nightly_extinction_scaled_mad": scaled_mad,
            "nightly_zero_point_mag": zero_point,
            "nightly_zero_point_uncertainty_mag": zero_uncertainty,
            "extinction_corrected_magnitude": extinction_corrected_magnitude,
            "extinction_correction_status": "available",
            "extinction_correction_source": calibration[
                "extinction_correction_source"
            ],
        })
        distance = distance_lookup.get(
            (row["planet"], row["observation_time_utc"])
        )
        if distance is None:
            row["extinction_correction_exclusion_reason"] = (
                "distance_ephemeris_unavailable"
            )
            calibration_audit.append(row)
            continue
        row.update(distance)
        uncertainty = uncertainty_lookup.get(
            (row["run_id"], str(row["detection_id"])), {}
        )
        row.update(uncertainty)
        measurement_uncertainty = _finite(
            row.get("machine_magnitude_uncertainty")
        )
        if measurement_uncertainty is None or measurement_uncertainty <= 0.0:
            row["extinction_correction_exclusion_reason"] = (
                row.get("uncertainty_status")
                or "photometric_uncertainty_unavailable"
            )
            calibration_audit.append(row)
            continue
        distance_corrected = _distance_corrected_magnitude(
            extinction_corrected_magnitude,
            row["sun_planet_distance_au"],
            row["earth_planet_distance_au"],
        )
        if distance_corrected is None:
            row["extinction_correction_exclusion_reason"] = (
                "distance_correction_failed"
            )
            calibration_audit.append(row)
            continue
        extinction_uncertainty = airmass * scaled_mad
        row["nightly_extinction_uncertainty_mag"] = extinction_uncertainty
        row["total_magnitude_uncertainty"] = math.sqrt(
            measurement_uncertainty ** 2
            + zero_uncertainty ** 2
            + extinction_uncertainty ** 2
        )
        row["distance_corrected_magnitude"] = _distance_corrected_magnitude(
            row["machine_magnitude"],
            row["sun_planet_distance_au"],
            row["earth_planet_distance_au"],
        )
        row["extinction_corrected_distance_magnitude"] = distance_corrected
        row["distance_correction_mag"] = extinction_corrected_magnitude - distance_corrected
        calibrated.append(row)
        calibration_audit.append(row)

    with (
        output / "planet_extinction_corrected_distance_measurements.csv"
    ).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=EXTINCTION_CORRECTED_DISTANCE_FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(calibrated)
    with (output / "planet_extinction_correction_audit.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=EXTINCTION_CORRECTED_DISTANCE_FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(calibration_audit)

    camera_markers = _camera_marker_map(calibrated)
    planet_colours = {
        planet: PLANET_COLOURS[planet]
        for planet in sorted({row["planet"] for row in calibrated})
    }
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "database": str(Path(database).resolve()),
        "nightly_calibration": str(
            Path(nightly_calibration).expanduser().resolve()
        ),
        "channel": channel,
        "quantity": "extinction-corrected, distance-corrected magnitude",
        "formula": (
            "m_calibrated = m_machine - Z_fixed - k_night * planet_airmass; "
            "m_calibrated_1_1 = m_calibrated "
            "- 5 log10(sun_planet_distance_AU * earth_planet_distance_AU)"
        ),
        "calibration_policy": (
            "Only accepted reference_ols sidecar rows with the exact source SHA-256, "
            "catalogue SHA-256, Arizona observing night, and channel are used; "
            "there is no legacy or raw fallback."
        ),
        "planet_identity_policy": (
            "Planets are associated downstream at the MMTO manifest UTC from "
            "saved detections, the fixed stellar-only camera, and the saved "
            "image-derived zenith. Blind fitted-epoch identities are not used."
        ),
        "uncertainty": (
            "Quadrature sum of empirical aperture uncertainty, fixed-image "
            "zero-point uncertainty, and planet airmass times the nightly scaled MAD."
        ),
        "plot_selection": {
            "skip_earliest_observations": skip_earliest_observations,
            "observations_omitted": len(omitted_observations),
            "measurements_omitted": len(rows) - len(audit_candidates),
        },
        "plotted_counts": {
            "measurements": len(calibrated),
            "unique_source_images": len({
                row["source_sha256"] or row["source_path"]
                for row in calibrated
            }),
            "by_planet": dict(Counter(row["planet"] for row in calibrated)),
        },
        "excluded_incomplete_calibrated_rows": (
            len(calibration_audit) - len(calibrated)
        ),
        "excluded_calibrated_reasons": dict(Counter(
            row.get("extinction_correction_exclusion_reason", "unspecified")
            for row in calibration_audit
            if row.get("extinction_correction_exclusion_reason")
        )),
        "source_detection_audit": audit,
    }
    (output / "extinction_corrected_distance_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    figure, _ = _build_extinction_corrected_distance_figure(
        calibrated, camera_markers, planet_colours, channel=channel
    )
    import matplotlib.pyplot as plt
    figure.savefig(
        output / "planet_extinction_corrected_distance_magnitude_vs_time.png",
        dpi=180,
    )
    figure.savefig(
        output / "planet_extinction_corrected_distance_magnitude_vs_time.pdf"
    )
    plt.close(figure)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract finalized planet photometry from stars.sqlite."
    )
    parser.add_argument("--database", type=Path, default=ROOT / "results" / "stars.sqlite")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--channel", choices="RGB", default="G")
    output_mode = parser.add_mutually_exclusive_group()
    output_mode.add_argument(
        "--distance-corrected",
        action="store_true",
        help=(
            "write the JPL-Horizons distance-normalized plot with empirical "
            "background-only uncertainty bars"
        ),
    )
    output_mode.add_argument(
        "--stellar-calibrated-distance-corrected",
        action="store_true",
        help=(
            "apply the same-run stellar zero point and extinction at the "
            "planet altitude, then normalize both planet distances"
        ),
    )
    output_mode.add_argument(
        "--extinction-corrected-distance-corrected",
        dest="extinction_corrected_distance_corrected",
        action="store_true",
        help=(
            "apply the exact nightly reference_ols sidecar zero point and "
            "extinction, then normalize both planet distances"
        ),
    )
    parser.add_argument(
        "--nightly-calibration",
        type=Path,
        help="sidecar directory containing nightly coefficients and image zero points",
    )
    parser.add_argument(
        "--skip-earliest-observations",
        type=int,
        default=0,
        metavar="N",
        help="omit the N chronologically earliest complete source images from the plot",
    )
    args = parser.parse_args(argv)
    if args.skip_earliest_observations < 0:
        parser.error("--skip-earliest-observations must be nonnegative")
    if (
        args.extinction_corrected_distance_corrected
        and args.nightly_calibration is None
    ):
        parser.error(
            "--extinction-corrected-distance-corrected requires "
            "--nightly-calibration DIR"
        )
    writer_arguments = {}
    if args.extinction_corrected_distance_corrected:
        rows, audit = load_mmto_metadata_planet_measurements(
            args.database,
            args.nightly_calibration,
            channel=args.channel,
        )
        writer = write_extinction_corrected_distance_outputs
        writer_arguments["nightly_calibration"] = args.nightly_calibration
    else:
        rows, audit = load_planet_measurements(args.database, args.channel)
        if args.stellar_calibrated_distance_corrected:
            writer = write_stellar_calibrated_distance_outputs
        elif args.distance_corrected:
            writer = write_distance_corrected_outputs
        else:
            writer = write_outputs
    summary = writer(
        rows, audit, args.output, database=args.database, channel=args.channel,
        skip_earliest_observations=args.skip_earliest_observations,
        **writer_arguments,
    )
    print(
        f"Planet photometry: {audit.get('detected_planet_rows', 0)} detections, "
        f"{summary['plotted_counts']['measurements']} plotted "
        f"{args.channel}-channel points"
    )
    print(f"Outputs: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
