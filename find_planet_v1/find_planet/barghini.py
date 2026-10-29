"""Invert saved Barghini O/Z cameras without consulting object predictions.

The detector mapping follows Barghini et al. (2019), equations 5, 6 and 11,
with the saved Borovicka radial law ``u(r)=v*r+s*expm1(d*r)``.  Saved
integrated refraction is removed once while going from an apparent detector ray
to its vacuum ICRS ray, and applied once for the inverse projection.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import brentq

from .types import AnonymousDirection, CameraReceipt, SelectedCentroid


ARCSEC_TO_RAD = math.radians(1.0 / 3600.0)
PARAMETER_NAMES = ("a0", "x_o", "y_o", "x_z", "y_z", "v", "s", "d")


def _normalise(vector: np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(value))
    if value.shape != (3,) or not np.isfinite(value).all() or norm <= 0.0:
        raise ValueError("sky direction must be a finite nonzero 3-vector")
    return value / norm


def _radial_u(radius: np.ndarray | float, v: float, s: float, d: float) -> np.ndarray:
    return v * np.asarray(radius, dtype=float) + s * np.expm1(d * np.asarray(radius, dtype=float))


def _radial_slope(radius: np.ndarray, v: float, s: float, d: float) -> np.ndarray:
    return v + s * d * np.exp(d * radius)


def _wrap_signed(angle: np.ndarray | float) -> np.ndarray:
    return (np.asarray(angle, dtype=float) + np.pi) % (2.0 * np.pi) - np.pi


def _camera_values(receipt: CameraReceipt) -> tuple[dict[str, float], np.ndarray, tuple[int, int], int, float]:
    record = receipt.camera
    if record.get("model") != "Barghini_2019_equations_5_6_11":
        raise ValueError("unsupported saved camera model")
    raw_parameters = record.get("parameters")
    if not isinstance(raw_parameters, Mapping):
        raise ValueError("saved camera parameters are missing")
    try:
        parameters = {name: float(raw_parameters[name]) for name in PARAMETER_NAMES}
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("saved camera parameters are incomplete") from error
    if not np.isfinite(list(parameters.values())).all():
        raise ValueError("saved camera parameters must be finite")

    rotation = np.asarray(record.get("reference_rotation"), dtype=float)
    if rotation.shape != (3, 3) or not np.isfinite(rotation).all():
        raise ValueError("saved camera rotation must be a finite 3x3 matrix")
    if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-9) or not math.isclose(
        float(np.linalg.det(rotation)), 1.0, abs_tol=1e-9
    ):
        raise ValueError("saved camera rotation must be a proper orthonormal rotation")

    shape_values = record.get("shape")
    if not isinstance(shape_values, (list, tuple)) or len(shape_values) != 2:
        raise ValueError("saved camera shape must contain height and width")
    shape = (int(shape_values[0]), int(shape_values[1]))
    if min(shape) <= 1:
        raise ValueError("saved camera shape must be positive")

    parity_name = record.get("detector_parity", "normal")
    if parity_name not in ("normal", "mirrored"):
        raise ValueError("saved camera parity must be normal or mirrored")
    parity = 1 if parity_name == "normal" else -1
    if record.get("monotonic_on_detector") is False:
        raise ValueError("saved camera declares a non-monotonic detector mapping")

    h, w = shape
    corners = np.array([[0.0, 0.0], [w - 1.0, 0.0], [0.0, h - 1.0], [w - 1.0, h - 1.0]])
    corner_radius = float(
        np.max(np.linalg.norm(corners - [parameters["x_o"], parameters["y_o"]], axis=1))
    )
    radii = np.linspace(0.0, corner_radius, 1025)
    slopes = _radial_slope(radii, parameters["v"], parameters["s"], parameters["d"])
    if not np.isfinite(slopes).all() or np.any(slopes <= 0.0):
        raise ValueError("saved camera radial mapping is not monotonic on the detector")
    endpoint = float(_radial_u(corner_radius, parameters["v"], parameters["s"], parameters["d"]))
    if not math.isfinite(endpoint) or endpoint <= 0.0 or endpoint >= math.pi + 1e-6:
        raise ValueError("saved camera radial endpoint is outside the invertible spherical domain")
    return parameters, rotation, shape, parity, corner_radius


def _derived_axis(parameters: Mapping[str, float]) -> tuple[float, float]:
    dx = parameters["x_o"] - parameters["x_z"]
    dy = parameters["y_o"] - parameters["y_z"]
    radius = math.hypot(dx, dy)
    e = float((parameters["a0"] + math.atan2(dy, dx)) % (2.0 * math.pi))
    epsilon = float(_radial_u(radius, parameters["v"], parameters["s"], parameters["d"]))
    return e, epsilon


def _detector_to_horizontal(x: float, y: float, parameters: Mapping[str, float]) -> tuple[float, float]:
    dx = x - parameters["x_o"]
    dy = y - parameters["y_o"]
    radius = math.hypot(dx, dy)
    e, epsilon = _derived_axis(parameters)
    b = parameters["a0"] - e + math.atan2(dy, dx)
    u = float(_radial_u(radius, parameters["v"], parameters["s"], parameters["d"]))
    numerator = math.sin(b) * math.sin(u)
    denominator = math.cos(b) * math.sin(u) * math.cos(epsilon) + math.cos(u) * math.sin(epsilon)
    azimuth = (e + math.atan2(numerator, denominator)) % (2.0 * math.pi)
    cos_z = math.cos(u) * math.cos(epsilon) - math.cos(b) * math.sin(u) * math.sin(epsilon)
    return azimuth, math.acos(float(np.clip(cos_z, -1.0, 1.0)))


def _inverse_radius(value: float, parameters: Mapping[str, float], corner_radius: float) -> float:
    if value <= 1e-15:
        return 0.0
    endpoint = float(
        _radial_u(corner_radius, parameters["v"], parameters["s"], parameters["d"])
    )
    if value > endpoint + 1e-10:
        raise ValueError("sky direction lies outside the saved detector domain")
    return float(
        brentq(
            lambda radius: float(
                _radial_u(radius, parameters["v"], parameters["s"], parameters["d"])
            )
            - value,
            0.0,
            corner_radius,
            xtol=1e-12,
            rtol=1e-14,
        )
    )


def _horizontal_to_detector(
    azimuth: float,
    zenith_distance: float,
    parameters: Mapping[str, float],
    corner_radius: float,
) -> np.ndarray:
    e, epsilon = _derived_axis(parameters)
    delta = float(_wrap_signed(azimuth - e))
    x_horizontal = math.sin(zenith_distance) * math.cos(delta)
    y_horizontal = math.sin(zenith_distance) * math.sin(delta)
    z_horizontal = math.cos(zenith_distance)
    x_projection = x_horizontal * math.cos(epsilon) - z_horizontal * math.sin(epsilon)
    y_projection = y_horizontal
    z_projection = x_horizontal * math.sin(epsilon) + z_horizontal * math.cos(epsilon)
    b = math.atan2(y_projection, x_projection)
    u = math.acos(float(np.clip(z_projection, -1.0, 1.0)))
    radius = _inverse_radius(u, parameters, corner_radius)
    detector_angle = b - parameters["a0"] + e
    return np.array(
        [
            parameters["x_o"] + radius * math.cos(detector_angle),
            parameters["y_o"] + radius * math.sin(detector_angle),
        ]
    )


def _refraction_record(record: Mapping[str, Any]) -> tuple[str, np.ndarray, float, float]:
    refraction = record.get("integrated_refraction")
    if not isinstance(refraction, Mapping):
        return "legacy_zero", np.array([0.0, 0.0, 1.0]), 0.0, 0.0
    status = str(refraction.get("status", "unknown"))
    zenith = _normalise(np.asarray(refraction.get("zenith_camera_unit_vector"), dtype=float))
    a = float(refraction.get("refraction_a_arcsec", 0.0))
    b = float(refraction.get("refraction_b_arcsec", 0.0))
    if not np.isfinite([a, b]).all():
        raise ValueError("saved refraction coefficients must be finite")
    return status, zenith, a, b


def _refract(vacuum: np.ndarray, zenith: np.ndarray, a_arcsec: float, b_arcsec: float) -> np.ndarray:
    vacuum = _normalise(vacuum)
    cosine = float(np.clip(vacuum @ zenith, -1.0, 1.0))
    distance = math.acos(cosine)
    if distance >= math.radians(88.5):
        raise ValueError("sky direction lies outside the supported refraction domain")
    tangent = math.tan(distance)
    displacement = ARCSEC_TO_RAD * (a_arcsec * tangent + b_arcsec * tangent**3)
    apparent_distance = max(distance - displacement, 0.0)
    transverse = vacuum - cosine * zenith
    norm = float(np.linalg.norm(transverse))
    if norm <= 1e-12:
        return zenith.copy()
    direction = transverse / norm
    return _normalise(math.cos(apparent_distance) * zenith + math.sin(apparent_distance) * direction)


def _derefract(apparent: np.ndarray, zenith: np.ndarray, a_arcsec: float, b_arcsec: float) -> np.ndarray:
    apparent = _normalise(apparent)
    cosine = float(np.clip(apparent @ zenith, -1.0, 1.0))
    apparent_distance = math.acos(cosine)
    vacuum_distance = apparent_distance
    a = a_arcsec * ARCSEC_TO_RAD
    b = b_arcsec * ARCSEC_TO_RAD
    for _ in range(15):
        if vacuum_distance >= math.radians(88.5):
            raise ValueError("detector ray lies outside the supported refraction domain")
        tangent = math.tan(vacuum_distance)
        function = vacuum_distance - a * tangent - b * tangent**3 - apparent_distance
        sec2 = 1.0 / math.cos(vacuum_distance) ** 2
        derivative = 1.0 - a * sec2 - 3.0 * b * tangent**2 * sec2
        if not math.isfinite(derivative) or derivative <= 0.05:
            raise ValueError("saved refraction mapping is not invertible")
        step = function / derivative
        vacuum_distance -= step
        if abs(step) < 1e-13:
            break
    transverse = apparent - cosine * zenith
    norm = float(np.linalg.norm(transverse))
    if norm <= 1e-12:
        return zenith.copy()
    direction = transverse / norm
    return _normalise(math.cos(vacuum_distance) * zenith + math.sin(vacuum_distance) * direction)


def camera_to_icrs_unit(camera: CameraReceipt, x_px: float, y_px: float) -> np.ndarray:
    parameters, rotation, shape, parity, _ = _camera_values(camera)
    h, w = shape
    if not np.isfinite([x_px, y_px]).all() or not (0.0 <= x_px <= w - 1 and 0.0 <= y_px <= h - 1):
        raise ValueError("measured centroid lies outside the saved detector")
    azimuth, zenith_distance = _detector_to_horizontal(float(x_px), float(y_px), parameters)
    ray = np.array(
        [
            math.sin(zenith_distance) * math.cos(azimuth),
            math.sin(zenith_distance) * math.sin(azimuth),
            math.cos(zenith_distance),
        ]
    )
    ray[1] *= parity
    _, refraction_zenith, a, b = _refraction_record(camera.camera)
    if a != 0.0 or b != 0.0:
        ray = _derefract(ray, refraction_zenith, a, b)
    return _normalise(ray @ rotation.T)


def icrs_unit_to_camera(camera: CameraReceipt, unit: np.ndarray) -> np.ndarray:
    parameters, rotation, shape, parity, corner_radius = _camera_values(camera)
    ray = _normalise(unit) @ rotation
    _, refraction_zenith, a, b = _refraction_record(camera.camera)
    if a != 0.0 or b != 0.0:
        ray = _refract(ray, refraction_zenith, a, b)
    ray[1] *= parity
    azimuth = math.atan2(float(ray[1]), float(ray[0]))
    zenith_distance = math.atan2(float(np.linalg.norm(ray[:2])), float(ray[2]))
    point = _horizontal_to_detector(azimuth, zenith_distance, parameters, corner_radius)
    h, w = shape
    if not (-1e-6 <= point[0] <= w - 1 + 1e-6 and -1e-6 <= point[1] <= h - 1 + 1e-6):
        raise ValueError("sky direction projects outside the saved detector")
    return point


def anonymous_direction_rows(
    centroids: Sequence[SelectedCentroid],
    receipts: Mapping[str, CameraReceipt],
) -> list[AnonymousDirection]:
    output: list[AnonymousDirection] = []
    for centroid in centroids:
        try:
            receipt = receipts[centroid.run_id]
        except KeyError as error:
            raise ValueError(f"missing exact camera receipt for {centroid.run_id}") from error
        direction = camera_to_icrs_unit(receipt, centroid.x_px, centroid.y_px)
        refraction_status, _, _, _ = _refraction_record(receipt.camera)
        output.append(
            AnonymousDirection(
                object_id="Object A",
                run_id=centroid.run_id,
                source_sha256=centroid.source_sha256,
                source_path=centroid.source_path,
                night=centroid.night,
                observation_time_utc=centroid.observation_time_utc,
                detection_id=centroid.detection_id,
                x_px=float(centroid.x_px),
                y_px=float(centroid.y_px),
                icrs_unit=tuple(float(value) for value in direction),
                stellar_fit_rms_arcmin=float(centroid.stellar_fit_rms_arcmin),
                source_class=centroid.source_class,
                saturated=bool(centroid.saturated),
                integrated_refraction_status=refraction_status,
            )
        )
    return output
