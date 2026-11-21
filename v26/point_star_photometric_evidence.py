"""Typed image-derived brightness evidence for planet-candidate ranking.

Direct aperture measurements and accepted saturated-wing models are estimates.
A clipped saturated aperture is retained as a flux lower bound.  This module
does not fit the zenith/extinction model and does not use site or time metadata.
"""
from __future__ import annotations

import math
from typing import Mapping, Any

from point_star_zenith import airmass


UNCERTAINTY_FLOOR_MAG = {
    "direct_aperture": 1.5,
    "psf_wing_model": 1.8,
    "saturated_aperture_lower_bound": 2.0,
}


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _true(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _unavailable(reason: str, *, channel: str, detection_id: str) -> dict:
    return {
        "status": "unavailable",
        "reason": reason,
        "channel": channel,
        "detection_id": detection_id,
    }


def measurement_evidence(
    photometry: Mapping[str, Any], channel: str = "G"
) -> dict:
    """Classify one saved channel measurement without discarding saturation."""
    prefix = f"{channel}_"
    identity = str(photometry.get("detection_id", ""))
    if not _true(photometry.get(prefix + "photometry_usable", False)):
        reason = str(photometry.get(prefix + "photometry_exclusion_reason", ""))
        return _unavailable(
            reason or "channel_photometry_unavailable",
            channel=channel,
            detection_id=identity,
        )

    aperture_rate = _float(photometry.get(prefix + "count_rate_adu_per_s"))
    saturated = _true(photometry.get(prefix + "saturated", False))
    if not saturated:
        if not math.isfinite(aperture_rate) or aperture_rate <= 0:
            return _unavailable(
                "nonpositive_or_nonfinite_count_rate",
                channel=channel,
                detection_id=identity,
            )
        return {
            "status": "available",
            "kind": "direct_aperture",
            "relation": "estimate",
            "channel": channel,
            "detection_id": identity,
            "count_rate_adu_per_s": aperture_rate,
            "uncertainty_floor_mag": UNCERTAINTY_FLOOR_MAG["direct_aperture"],
        }

    wing_status = str(photometry.get(prefix + "wing_fit_status", ""))
    wing_rate = _float(photometry.get(prefix + "wing_fit_count_rate_adu_per_s"))
    if (wing_status == "modelled_from_unsaturated_wings"
            and math.isfinite(wing_rate) and wing_rate > 0):
        return {
            "status": "available",
            "kind": "psf_wing_model",
            "relation": "estimate",
            "channel": channel,
            "detection_id": identity,
            "count_rate_adu_per_s": wing_rate,
            "wing_fit_status": wing_status,
            "uncertainty_floor_mag": UNCERTAINTY_FLOOR_MAG["psf_wing_model"],
        }

    if math.isfinite(aperture_rate) and aperture_rate > 0:
        return {
            "status": "available",
            "kind": "saturated_aperture_lower_bound",
            "relation": "flux_lower_bound",
            "channel": channel,
            "detection_id": identity,
            "count_rate_adu_per_s": aperture_rate,
            "wing_fit_status": wing_status or "unavailable",
            "uncertainty_floor_mag": UNCERTAINTY_FLOOR_MAG[
                "saturated_aperture_lower_bound"
            ],
        }
    return _unavailable(
        "saturated_source_has_no_positive_flux_evidence",
        channel=channel,
        detection_id=identity,
    )


def matched_planet_evidence(
    *,
    planet: str,
    predicted_v_mag: float,
    altitude_deg: float,
    radial_squared: float,
    photometry: Mapping[str, Any],
    calibration: Mapping[str, Any],
    channel: str = "G",
) -> dict:
    """Compare a candidate magnitude with one typed image measurement."""
    measurement = measurement_evidence(photometry, channel)
    predicted_v_value = _float(predicted_v_mag)
    base = {
        "planet": planet,
        "predicted_v_mag": (predicted_v_value
                            if math.isfinite(predicted_v_value) else None),
        "measurement": measurement,
    }
    if measurement["status"] != "available":
        return {**base, "status": "unavailable", "reason": measurement["reason"]}

    altitude = _float(altitude_deg)
    radial = _float(radial_squared)
    x = float(airmass([altitude])[0])
    if not (math.isfinite(x) and math.isfinite(radial)):
        return {**base, "status": "unavailable",
                "reason": "invalid_photometric_geometry"}

    intercept = _float(calibration.get("intercept_mag"))
    extinction = _float(calibration.get(
        "extinction_mag_per_airmass",
        calibration.get("coefficient_mag_per_airmass"),
    ))
    radial_coefficient = _float(calibration.get("radial_coefficient_mag", 0.0))
    predicted_v = predicted_v_value
    if not all(math.isfinite(value) for value in (
            intercept, extinction, radial_coefficient, predicted_v)):
        return {**base, "status": "unavailable",
                "reason": "photometric_calibration_unavailable"}

    rate = float(measurement["count_rate_adu_per_s"])
    measured_mag = -2.5 * math.log10(rate)
    predicted_mag = (
        predicted_v + intercept + extinction * x + radial_coefficient * radial
    )
    raw_residual = predicted_mag - measured_mag
    residual = (max(0.0, raw_residual)
                if measurement["relation"] == "flux_lower_bound"
                else raw_residual)
    rms = _float(calibration.get("rms_mag", 0.0))
    if not math.isfinite(rms) or rms < 0:
        rms = 0.0
    sigma = math.hypot(float(measurement["uncertainty_floor_mag"]), rms)
    standardised = residual / sigma
    cost = math.sqrt(1.0 + standardised * standardised) - 1.0
    return {
        **base,
        "status": "available",
        "airmass": x,
        "radial_squared": radial,
        "measured_instrumental_mag": measured_mag,
        "predicted_instrumental_mag": predicted_mag,
        "magnitude_residual": residual,
        "uncertainty_mag": sigma,
        "standardised_residual": standardised,
        "cost": cost,
        "loss": "soft_l1",
    }
