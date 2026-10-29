from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from .types import AnonymousDirection, CameraReceipt, SelectedCentroid


ARCSEC_TO_RAD = math.radians(1.0 / 3600.0)
PARAMETER_NAMES = ("a0", "x_o", "y_o", "x_z", "y_z", "v", "s", "d")


def _normalise(vector: np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=float)
    norm = float(np.linalg.norm(value))
    if value.shape != (3,) or not np.isfinite(value).all() or norm <= 0:
        raise ValueError("sky direction must be a finite nonzero 3-vector")
    return value / norm


def _radial_u(radius: np.ndarray | float, v: float, s: float, d: float) -> np.ndarray:
    value = np.asarray(radius, dtype=float)
    return v * value + s * np.expm1(d * value)


def _radial_slope(radius: np.ndarray, v: float, s: float, d: float) -> np.ndarray:
    return v + s * d * np.exp(d * radius)


def _camera_values(receipt: CameraReceipt) -> tuple[dict[str, float], np.ndarray, tuple[int, int], int, float]:
    record = receipt.camera
    if record.get("model") != "Barghini_2019_equations_5_6_11":
        raise ValueError("unsupported saved camera model")
    raw = record.get("parameters")
    if not isinstance(raw, Mapping):
        raise ValueError("saved camera parameters are missing")
    try:
        parameters = {name: float(raw[name]) for name in PARAMETER_NAMES}
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("saved camera parameters are incomplete") from error
    if not np.isfinite(list(parameters.values())).all():
        raise ValueError("saved camera parameters must be finite")
    rotation = np.asarray(record.get("reference_rotation"), dtype=float)
    if rotation.shape != (3, 3) or not np.isfinite(rotation).all():
        raise ValueError("saved camera rotation must be a finite 3x3 matrix")
    if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-9) or not math.isclose(float(np.linalg.det(rotation)), 1.0, abs_tol=1e-9):
        raise ValueError("saved camera rotation must be proper and orthonormal")
    raw_shape = record.get("shape")
    if not isinstance(raw_shape, (list, tuple)) or len(raw_shape) != 2:
        raise ValueError("saved camera shape must contain height and width")
    shape = (int(raw_shape[0]), int(raw_shape[1]))
    if min(shape) <= 1:
        raise ValueError("saved camera shape must be positive")
    parity_name = record.get("detector_parity", "normal")
    if parity_name not in {"normal", "mirrored"}:
        raise ValueError("saved camera parity must be normal or mirrored")
    if record.get("monotonic_on_detector") is False:
        raise ValueError("saved camera declares a non-monotonic detector mapping")
    h, w = shape
    corners = np.array([[0.0, 0.0], [w - 1.0, 0.0], [0.0, h - 1.0], [w - 1.0, h - 1.0]])
    corner_radius = float(np.max(np.linalg.norm(corners - [parameters["x_o"], parameters["y_o"]], axis=1)))
    radii = np.linspace(0.0, corner_radius, 1025)
    slopes = _radial_slope(radii, parameters["v"], parameters["s"], parameters["d"])
    if not np.isfinite(slopes).all() or np.any(slopes <= 0):
        raise ValueError("saved camera radial mapping is not monotonic on the detector")
    return parameters, rotation, shape, 1 if parity_name == "normal" else -1, corner_radius


def _derived_axis(parameters: Mapping[str, float]) -> tuple[float, float]:
    dx, dy = parameters["x_o"] - parameters["x_z"], parameters["y_o"] - parameters["y_z"]
    radius = math.hypot(dx, dy)
    e = (parameters["a0"] + math.atan2(dy, dx)) % (2 * math.pi)
    epsilon = float(_radial_u(radius, parameters["v"], parameters["s"], parameters["d"]))
    return e, epsilon


def _detector_to_horizontal(x: float, y: float, parameters: Mapping[str, float]) -> tuple[float, float]:
    dx, dy = x - parameters["x_o"], y - parameters["y_o"]
    e, epsilon = _derived_axis(parameters)
    b = parameters["a0"] - e + math.atan2(dy, dx)
    u = float(_radial_u(math.hypot(dx, dy), parameters["v"], parameters["s"], parameters["d"]))
    numerator = math.sin(b) * math.sin(u)
    denominator = math.cos(b) * math.sin(u) * math.cos(epsilon) + math.cos(u) * math.sin(epsilon)
    azimuth = (e + math.atan2(numerator, denominator)) % (2 * math.pi)
    cos_z = math.cos(u) * math.cos(epsilon) - math.cos(b) * math.sin(u) * math.sin(epsilon)
    return azimuth, math.acos(float(np.clip(cos_z, -1, 1)))


def _inverse_radius(value: float, parameters: Mapping[str, float], corner_radius: float) -> float:
    if value <= 1e-15:
        return 0.0
    endpoint = float(_radial_u(corner_radius, parameters["v"], parameters["s"], parameters["d"]))
    if value > endpoint + 1e-10:
        raise ValueError("sky direction lies outside the saved detector domain")
    low, high = 0.0, corner_radius
    for _ in range(80):
        midpoint = (low + high) / 2
        mapped = float(_radial_u(midpoint, parameters["v"], parameters["s"], parameters["d"]))
        if mapped < value:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2


def _horizontal_to_detector(azimuth: float, zenith_distance: float, parameters: Mapping[str, float], corner_radius: float) -> np.ndarray:
    e, epsilon = _derived_axis(parameters)
    delta = (azimuth - e + math.pi) % (2 * math.pi) - math.pi
    horizontal = np.array([
        math.sin(zenith_distance) * math.cos(delta),
        math.sin(zenith_distance) * math.sin(delta),
        math.cos(zenith_distance),
    ])
    projection = np.array([
        horizontal[0] * math.cos(epsilon) - horizontal[2] * math.sin(epsilon),
        horizontal[1],
        horizontal[0] * math.sin(epsilon) + horizontal[2] * math.cos(epsilon),
    ])
    b = math.atan2(float(projection[1]), float(projection[0]))
    u = math.acos(float(np.clip(projection[2], -1, 1)))
    radius = _inverse_radius(u, parameters, corner_radius)
    detector_angle = b - parameters["a0"] + e
    return np.array([parameters["x_o"] + radius * math.cos(detector_angle), parameters["y_o"] + radius * math.sin(detector_angle)])


def _refraction_record(record: Mapping[str, Any]) -> tuple[str, np.ndarray, float, float]:
    refraction = record.get("integrated_refraction")
    if not isinstance(refraction, Mapping):
        return "legacy_zero", np.array([0.0, 0.0, 1.0]), 0.0, 0.0
    zenith = _normalise(np.asarray(refraction.get("zenith_camera_unit_vector"), dtype=float))
    a, b = float(refraction.get("refraction_a_arcsec", 0.0)), float(refraction.get("refraction_b_arcsec", 0.0))
    if not np.isfinite([a, b]).all():
        raise ValueError("saved refraction coefficients must be finite")
    return str(refraction.get("status", "unknown")), zenith, a, b


def _refract(vacuum: np.ndarray, zenith: np.ndarray, a_arcsec: float, b_arcsec: float) -> np.ndarray:
    vacuum = _normalise(vacuum)
    cosine = float(np.clip(vacuum @ zenith, -1, 1))
    distance = math.acos(cosine)
    if distance >= math.radians(88.5):
        raise ValueError("sky direction lies outside the supported refraction domain")
    tangent = math.tan(distance)
    apparent_distance = max(distance - ARCSEC_TO_RAD * (a_arcsec * tangent + b_arcsec * tangent**3), 0.0)
    transverse = vacuum - cosine * zenith
    norm = float(np.linalg.norm(transverse))
    if norm <= 1e-12:
        return zenith.copy()
    return _normalise(math.cos(apparent_distance) * zenith + math.sin(apparent_distance) * transverse / norm)


def _derefract(apparent: np.ndarray, zenith: np.ndarray, a_arcsec: float, b_arcsec: float) -> np.ndarray:
    apparent = _normalise(apparent)
    cosine = float(np.clip(apparent @ zenith, -1, 1))
    apparent_distance = math.acos(cosine)
    vacuum_distance = apparent_distance
    a, b = a_arcsec * ARCSEC_TO_RAD, b_arcsec * ARCSEC_TO_RAD
    for _ in range(15):
        limited = min(vacuum_distance, math.radians(88.5))
        tangent = math.tan(limited)
        function = vacuum_distance - a * tangent - b * tangent**3 - apparent_distance
        sec2 = 1 / math.cos(limited) ** 2
        derivative = 1 - a * sec2 - 3 * b * tangent**2 * sec2
        if math.isfinite(derivative) and abs(derivative) > 1e-8:
            vacuum_distance -= function / derivative
        vacuum_distance = float(np.clip(vacuum_distance, 0, math.radians(89)))
    transverse = apparent - cosine * zenith
    norm = float(np.linalg.norm(transverse))
    if norm <= 1e-12:
        return zenith.copy()
    return _normalise(math.cos(vacuum_distance) * zenith + math.sin(vacuum_distance) * transverse / norm)


def camera_to_icrs_unit(camera: CameraReceipt, x_px: float, y_px: float) -> np.ndarray:
    parameters, rotation, shape, parity, _ = _camera_values(camera)
    h, w = shape
    if not np.isfinite([x_px, y_px]).all() or not (0 <= x_px <= w - 1 and 0 <= y_px <= h - 1):
        raise ValueError("measured centroid lies outside the saved detector")
    radius = math.hypot(x_px - parameters["x_o"], y_px - parameters["y_o"])
    if float(_radial_u(radius, parameters["v"], parameters["s"], parameters["d"])) >= math.pi - 1e-10:
        raise ValueError("measured centroid lies beyond the one-to-one spherical camera domain")
    azimuth, zenith_distance = _detector_to_horizontal(x_px, y_px, parameters)
    ray = np.array([math.sin(zenith_distance) * math.cos(azimuth), math.sin(zenith_distance) * math.sin(azimuth), math.cos(zenith_distance)])
    ray[1] *= parity
    _, refraction_zenith, a, b = _refraction_record(camera.camera)
    if a != 0 or b != 0:
        ray = _derefract(ray, refraction_zenith, a, b)
    return _normalise(ray @ rotation.T)


def icrs_unit_to_camera(camera: CameraReceipt, unit: np.ndarray) -> np.ndarray:
    parameters, rotation, shape, parity, corner_radius = _camera_values(camera)
    ray = _normalise(unit) @ rotation
    _, refraction_zenith, a, b = _refraction_record(camera.camera)
    if a != 0 or b != 0:
        ray = _refract(ray, refraction_zenith, a, b)
    ray[1] *= parity
    point = _horizontal_to_detector(math.atan2(float(ray[1]), float(ray[0])), math.atan2(float(np.linalg.norm(ray[:2])), float(ray[2])), parameters, corner_radius)
    h, w = shape
    if not (-1e-6 <= point[0] <= w - 1 + 1e-6 and -1e-6 <= point[1] <= h - 1 + 1e-6):
        raise ValueError("sky direction projects outside the saved detector")
    return point


def anonymous_direction_rows(centroids: Sequence[SelectedCentroid], receipts: Mapping[str, CameraReceipt]) -> list[AnonymousDirection]:
    output = []
    for centroid in centroids:
        if centroid.run_id not in receipts:
            raise ValueError(f"missing exact camera receipt for {centroid.run_id}")
        receipt = receipts[centroid.run_id]
        direction = camera_to_icrs_unit(receipt, centroid.x_px, centroid.y_px)
        refraction_status, _, _, _ = _refraction_record(receipt.camera)
        output.append(AnonymousDirection(
            object_id="Object A", run_id=centroid.run_id, source_sha256=centroid.source_sha256,
            source_path=centroid.source_path, night=centroid.night,
            observation_time_utc=centroid.observation_time_utc, detection_id=centroid.detection_id,
            x_px=float(centroid.x_px), y_px=float(centroid.y_px),
            icrs_unit=tuple(float(value) for value in direction),
            stellar_fit_rms_arcmin=float(centroid.stellar_fit_rms_arcmin),
            source_class=centroid.source_class, saturated=bool(centroid.saturated),
            integrated_refraction_status=refraction_status,
        ))
    return output
