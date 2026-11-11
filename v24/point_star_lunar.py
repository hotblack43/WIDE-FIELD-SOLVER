"""Conservative topocentric lunar evidence for already-fitted planet dates.

The Moon is never treated as a point source and never changes the camera,
centroids, stellar associations, or fitted coordinates.  Candidate epochs and
the image-derived zenith imply an observer location; that location supplies the
topocentric parallax needed to ask whether the predicted lunar region contains
an extended/saturated signal or a well-supported blank.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import warnings

import erfa
import numpy as np

MOON_RADIUS_KM = 1737.4
MINIMUM_ILLUMINATION_FRACTION = 0.25
MINIMUM_ALTITUDE_DEG = 5.0
POSITION_GUARD_DEG = 0.75
MINIMUM_OBSERVED_DIAMETER_DEG = 0.5
MINIMUM_LUMINOUS_PEAK_SNR = 25.0


def _unit(vector, label):
    value = np.asarray(vector, dtype=float)
    norm = np.linalg.norm(value)
    if value.shape != (3,) or not np.isfinite(value).all() or norm <= 0:
        raise ValueError(f"{label} must be a finite nonzero three-vector")
    return value / norm


def predict_topocentric_moon(jd_tdb, zenith_unit_vector):
    """Predict the Moon from an epoch and image-derived zenith, without metadata."""
    from astropy import units as u
    from astropy.coordinates import EarthLocation, ICRS, ITRS, SkyCoord, get_body
    from astropy.time import Time
    from astropy.utils import iers
    from astropy.utils.exceptions import AstropyWarning

    date = float(jd_tdb)
    if not np.isfinite(date):
        raise ValueError("Lunar prediction needs a finite TDB Julian date")
    zenith = _unit(zenith_unit_vector, "Zenith")
    time = Time(date, format="jd", scale="tdb")
    direction = SkyCoord(
        x=zenith[0], y=zenith[1], z=zenith[2],
        representation_type="cartesian", frame=ICRS(),
    )
    with (warnings.catch_warnings(),
          iers.conf.set_temp("auto_download", False),
          iers.conf.set_temp("auto_max_age", None)):
        warnings.filterwarnings(
            "ignore", message=r"Tried to get polar motions.*", category=AstropyWarning
        )
        warnings.filterwarnings(
            "ignore", message=r'ERFA function ".*dubious year.*', category=erfa.ErfaWarning
        )
        warnings.filterwarnings(
            "ignore", message=r'ERFA function "epv00".*', category=erfa.ErfaWarning
        )
        earth_fixed = direction.transform_to(ITRS(obstime=time)).cartesian.xyz.value
    longitude = float(np.rad2deg(np.arctan2(earth_fixed[1], earth_fixed[0])))
    latitude = float(np.rad2deg(np.arctan2(
        earth_fixed[2], np.hypot(earth_fixed[0], earth_fixed[1])
    )))
    location = EarthLocation.from_geodetic(
        longitude * u.deg, latitude * u.deg, 0 * u.m
    )
    with (warnings.catch_warnings(),
          iers.conf.set_temp("auto_download", False),
          iers.conf.set_temp("auto_max_age", None)):
        warnings.filterwarnings(
            "ignore", message=r'ERFA function "epv00".*', category=erfa.ErfaWarning
        )
        warnings.filterwarnings(
            "ignore", message=r'ERFA function "(?:taiutc|utctai)".*dubious year.*',
            category=erfa.ErfaWarning,
        )
        warnings.filterwarnings(
            "ignore", message=r"Tried to get polar motions.*", category=AstropyWarning
        )
        moon = get_body("moon", time, location=location, ephemeris="builtin")
        sun = get_body("sun", time, location=location, ephemeris="builtin")
    moon_vector = _unit(moon.cartesian.xyz.value, "Moon direction")
    sun_vector = _unit(sun.cartesian.xyz.value, "Sun direction")
    elongation = float(np.rad2deg(np.arccos(np.clip(
        np.dot(moon_vector, sun_vector), -1.0, 1.0
    ))))
    illumination = float((1.0 - np.cos(np.deg2rad(elongation))) / 2.0)
    distance_km = float(moon.distance.to_value(u.km))
    angular_diameter = float(2.0 * np.rad2deg(np.arctan2(
        MOON_RADIUS_KM, distance_km
    )))
    return {
        "jd_tdb": date,
        "unit_vector": moon_vector.tolist(),
        "illumination_fraction": illumination,
        "sun_moon_elongation_deg": elongation,
        "angular_diameter_deg": angular_diameter,
        "distance_km": distance_km,
        "observer_longitude_deg": longitude,
        "observer_latitude_deg": latitude,
        "observer_height_m": 0.0,
        "observer_source": "candidate epoch plus image-derived zenith",
        "ephemeris": "Astropy builtin topocentric apparent GCRS",
        "earth_orientation_policy": (
            "bundled IERS only; predictive-age limit disabled; mean polar motion "
            "may be used outside the bundled table"
        ),
        "metadata_used": False,
    }


def _true(value):
    return str(value).lower() == "true"


def _project(camera, vector):
    try:
        point = np.asarray(camera.project(np.asarray(vector)[None, :])[0], dtype=float)
    except (ValueError, FloatingPointError):
        return None
    if point.shape != (2,) or not np.isfinite(point).all():
        return None
    height, width = camera.shape
    if not (0 <= point[0] <= width - 1 and 0 <= point[1] <= height - 1):
        return None
    try:
        inverse = _unit(camera.to_sky(point[None, :])[0], "Inverse projection")
    except (ValueError, FloatingPointError):
        return None
    if np.linalg.norm(inverse - vector) >= 1e-6:
        return None
    return point


def _projected_guard_radius(camera, vector, point, radius_deg):
    """Return the enclosing pixel radius, or None if guarded sky crosses an edge."""
    vector = _unit(vector, "Guarded Moon direction")
    reference = np.eye(3)[int(np.argmin(np.abs(vector)))]
    east = _unit(np.cross(reference, vector), "Lunar tangent basis")
    north = _unit(np.cross(vector, east), "Lunar tangent basis")
    radius = np.deg2rad(float(radius_deg))
    projected = []
    for angle in np.linspace(0.0, 2.0 * np.pi, 16, endpoint=False):
        tangent = np.cos(angle) * east + np.sin(angle) * north
        boundary = np.cos(radius) * vector + np.sin(radius) * tangent
        sample = _project(camera, _unit(boundary, "Lunar guard boundary"))
        if sample is None:
            return None
        projected.append(sample)
    return float(np.max(np.linalg.norm(np.asarray(projected) - point, axis=1)))


def _separation_deg(first, second):
    return float(np.rad2deg(np.arccos(np.clip(
        np.dot(_unit(first, "First direction"), _unit(second, "Second direction")),
        -1.0, 1.0,
    ))))


def _minor_angular_diameter(camera, detection):
    """Estimate a blob's resolved minor diameter using its sky projection."""
    area = float(detection.get("area_px", 0.0))
    axis_ratio = float(detection.get("axis_ratio", 1.0))
    if not np.isfinite([area, axis_ratio]).all() or area <= 0 or axis_ratio < 1:
        return 0.0
    radius_px = float(np.sqrt(area / (np.pi * axis_ratio)))
    centre = np.array([float(detection["x_px"]), float(detection["y_px"])])
    diameters = []
    for direction in np.linspace(0.0, np.pi, 8, endpoint=False):
        offset = radius_px * np.array([np.cos(direction), np.sin(direction)])
        try:
            rays = camera.to_sky(np.array([centre - offset, centre + offset]))
            diameters.append(_separation_deg(rays[0], rays[1]))
        except (ValueError, FloatingPointError):
            continue
    return min(diameters, default=0.0)


def identify_moon_candidates(camera, detections, stars, zenith_unit_vector, *,
                             valid_mask=None):
    """Return resolved image objects physically large enough to be the Moon."""
    zenith = _unit(zenith_unit_vector, "Moon-candidate zenith")
    identified_ids = {str(row.get("detection_id")) for row in stars}
    mask = None if valid_mask is None else np.asarray(valid_mask, dtype=bool)
    if mask is not None and mask.shape != tuple(camera.shape):
        raise ValueError("Moon-candidate mask shape differs from the image")
    rows = []
    for source in detections:
        if str(source.get("detection_id")) in identified_ids:
            continue
        if source.get("source_class") != "broad_blob" and not _true(
                source.get("saturated", False)):
            continue
        peak_snr = float(source.get("peak_snr", 0.0) or 0.0)
        if not _true(source.get("saturated", False)) and (
                not np.isfinite(peak_snr) or peak_snr < MINIMUM_LUMINOUS_PEAK_SNR):
            continue
        point = np.array([float(source["x_px"]), float(source["y_px"])])
        x, y = int(round(point[0])), int(round(point[1]))
        if (x < 0 or y < 0 or x >= camera.shape[1] or y >= camera.shape[0]
                or (mask is not None and not mask[y, x])):
            continue
        vector = _unit(camera.to_sky(point[None, :])[0], "Observed Moon candidate")
        altitude = float(np.rad2deg(np.arcsin(np.clip(
            np.dot(vector, zenith), -1.0, 1.0
        ))))
        diameter = _minor_angular_diameter(camera, source)
        if altitude < MINIMUM_ALTITUDE_DEG or diameter < MINIMUM_OBSERVED_DIAMETER_DEG:
            continue
        row = copy.deepcopy(source)
        row.update(
            unit_vector=vector.tolist(),
            altitude_deg=altitude,
            minor_angular_diameter_deg=diameter,
            minimum_lunar_diameter_deg=MINIMUM_OBSERVED_DIAMETER_DEG,
            minimum_luminous_peak_snr=MINIMUM_LUMINOUS_PEAK_SNR,
        )
        rows.append(row)
    return rows


def _base_record(prediction, zenith):
    vector = _unit(prediction["unit_vector"], "Predicted Moon")
    illumination = float(prediction["illumination_fraction"])
    diameter = float(prediction["angular_diameter_deg"])
    if not np.isfinite([illumination, diameter]).all() or not 0 <= illumination <= 1 or diameter <= 0:
        raise ValueError("Lunar prediction has invalid illumination or angular diameter")
    return {
        **copy.deepcopy(prediction),
        "unit_vector": vector.tolist(),
        "predicted_altitude_deg": float(np.rad2deg(np.arcsin(np.clip(
            np.dot(vector, zenith), -1.0, 1.0
        )))),
        "minimum_illumination_fraction": MINIMUM_ILLUMINATION_FRACTION,
        "minimum_altitude_deg": MINIMUM_ALTITUDE_DEG,
        "position_guard_deg": POSITION_GUARD_DEG,
        "selection_effect": "neutral",
    }


def _finish(record, status, effect="neutral", reason=None):
    record["status"] = status
    record["selection_effect"] = effect
    if reason:
        record["reason"] = reason
    return record


def _mask_covers_region(mask, point, radius_px):
    if radius_px is None or not np.isfinite(radius_px):
        return False
    x0 = max(0, int(np.floor(point[0] - radius_px)))
    x1 = min(mask.shape[1], int(np.ceil(point[0] + radius_px)) + 1)
    y0 = max(0, int(np.floor(point[1] - radius_px)))
    y1 = min(mask.shape[0], int(np.ceil(point[1] + radius_px)) + 1)
    if x0 == 0 or y0 == 0 or x1 == mask.shape[1] or y1 == mask.shape[0]:
        return False
    yy, xx = np.ogrid[y0:y1, x0:x1]
    inside = (xx - point[0]) ** 2 + (yy - point[1]) ** 2 <= radius_px ** 2
    return bool(np.all(mask[y0:y1, x0:x1][inside]))


def annotate_lunar_evidence(
    answer,
    camera,
    pixels,
    detections,
    stars,
    *,
    valid_mask=None,
    prediction_function=predict_topocentric_moon,
):
    """Attach lunar evidence to every retained date without selecting a new date."""
    out = copy.deepcopy(answer)
    candidates = out.get("candidates") or []
    pixels = np.asarray(pixels, dtype=float)
    if pixels.ndim == 3:
        pixels = pixels[..., :3] @ np.array([0.2126, 0.7152, 0.0722])
    if pixels.ndim != 2 or tuple(pixels.shape) != tuple(camera.shape):
        raise ValueError("Lunar evidence image shape differs from the fixed camera")
    mask = np.isfinite(pixels) if valid_mask is None else (
        np.asarray(valid_mask, dtype=bool) & np.isfinite(pixels)
    )
    if mask.shape != pixels.shape:
        raise ValueError("Lunar evidence mask shape differs from the image")
    visibility = out.get("visibility") or {}
    zenith_value = visibility.get("zenith_unit_vector")
    if zenith_value is None:
        for candidate in candidates:
            candidate["lunar_evidence"] = {
                "status": "unresolved_no_image_zenith",
                "selection_effect": "neutral",
                "metadata_used": False,
            }
        out["lunar_evidence"] = {
            "status": "unresolved_no_image_zenith",
            "candidate_count": len(candidates),
            "metadata_used": False,
        }
        return out
    zenith = _unit(zenith_value, "Lunar evidence zenith")
    moon_sources = identify_moon_candidates(
        camera, list(detections), list(stars), zenith, valid_mask=mask
    )
    records = []
    for candidate in candidates:
        prediction = prediction_function(float(candidate["jd_tdb"]), zenith.copy())
        record = _base_record(prediction, zenith)
        altitude = record["predicted_altitude_deg"]
        if -MINIMUM_ALTITUDE_DEG <= altitude <= MINIMUM_ALTITUDE_DEG:
            row = _finish(
                record, "inconclusive_near_horizon", "neutral",
                "The predicted Moon lies inside the five-degree horizon guard",
            )
        elif moon_sources and altitude > MINIMUM_ALTITUDE_DEG:
            source = moon_sources[0]
            record["detection_id"] = int(source["detection_id"])
            record["detection_source_class"] = source.get("source_class")
            record["detection_saturated"] = _true(source.get("saturated", False))
            record["observed_minor_angular_diameter_deg"] = source[
                "minor_angular_diameter_deg"
            ]
            row = _finish(
                record, "lunar_signal_present", "support",
                "A bright resolved Moon-sized object and the predicted Moon are both above the guarded horizon",
            )
        elif moon_sources:
            row = _finish(
                record, "observed_moon_not_predicted", "contradict",
                "A bright resolved Moon-sized object is above the image horizon, but the predicted Moon is below it",
            )
        elif altitude > MINIMUM_ALTITUDE_DEG:
            row = _finish(
                record, "missing_expected_moon", "contradict",
                "The predicted Moon is above the guarded horizon, but no bright resolved Moon-sized object is present",
            )
        else:
            row = _finish(
                record, "moon_below_horizon", "neutral",
                "No bright resolved Moon-sized object is present and the predicted Moon is below the guarded horizon",
            )
        records.append(row)
        candidate["lunar_evidence"] = row

    out["lunar_evidence"] = {
        "status": "assessed" if candidates else "no_planet_date_candidates",
        "method": "binary bright Moon-sized image presence and topocentric above/below-horizon compatibility",
        "candidate_count": len(records),
        "observed_moon_status": "present" if moon_sources else "absent",
        "observed_moon_candidates": moon_sources,
        "minimum_observed_diameter_deg": MINIMUM_OBSERVED_DIAMETER_DEG,
        "supporting_candidates": sum(row["selection_effect"] == "support" for row in records),
        "contradicted_candidates": sum(row["selection_effect"] == "contradict" for row in records),
        "neutral_candidates": sum(row["selection_effect"] == "neutral" for row in records),
        "minimum_altitude_deg": MINIMUM_ALTITUDE_DEG,
        "minimum_luminous_peak_snr": MINIMUM_LUMINOUS_PEAK_SNR,
        "metadata_used": False,
        "enters_camera_fit": False,
        "can_establish_epoch_alone": False,
        "limitation": (
            "A Moon candidate must have a resolved minor angular diameter of at least 0.5 degrees and be saturated or have peak S/N at least 25. "
            "The constraint uses only whether the observed and predicted Moon are above or below the five-degree guarded horizon; phase and positional coincidence do not enter."
        ),
    }
    return out


def write_lunar_evidence(image_path, output, answer, *, solution=None):
    """Write the machine-readable presence/absence audit; no trial-date carpet."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    record = {
        "summary": answer.get("lunar_evidence"),
        "candidates": [
            {
                "rank": index,
                "epoch_tdb": candidate.get("epoch_tdb"),
                "jd_tdb": candidate.get("jd_tdb"),
                "evidence": candidate.get("lunar_evidence"),
            }
            for index, candidate in enumerate(answer.get("candidates", []), 1)
        ],
    }
    (output / "lunar_evidence.json").write_text(
        json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
