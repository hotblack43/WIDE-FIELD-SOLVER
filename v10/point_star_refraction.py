from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


ARCSEC_TO_RAD = math.radians(1.0 / 3600.0)


@dataclass(frozen=True)
class AtmosphericRefractionFit:
    status: str
    zenith_camera: np.ndarray
    refraction_a_arcsec: float
    refraction_b_arcsec: float
    rotation_camera_to_icrs: np.ndarray
    corrected_camera_rays: np.ndarray
    baseline_rms_arcmin: float
    fitted_rms_arcmin: float
    delta_bic: float
    zenith_distance_range_deg: tuple[float, float]
    refraction_a_sigma_arcsec: float | None
    boundary_limited: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "model": "R(z) = A*tan(z) + B*tan(z)^3 towards a fitted zenith",
            "zenith_camera_unit_vector": self.zenith_camera.tolist(),
            "refraction_a_arcsec": self.refraction_a_arcsec,
            "refraction_b_arcsec": self.refraction_b_arcsec,
            "baseline_rms_arcmin": self.baseline_rms_arcmin,
            "fitted_rms_arcmin": self.fitted_rms_arcmin,
            "delta_bic": self.delta_bic,
            "zenith_distance_range_deg": list(self.zenith_distance_range_deg),
            "refraction_a_sigma_arcsec": self.refraction_a_sigma_arcsec,
            "boundary_limited": self.boundary_limited,
            "inputs": "matched image rays and catalogue directions only",
            "pressure_temperature_or_location_used": False,
        }


def _normalise(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float64)
    return vectors / np.linalg.norm(vectors, axis=1)[:, None]


def zenith_from_angles(azimuth_rad: float, inclination_rad: float) -> np.ndarray:
    return np.array(
        [
            math.sin(inclination_rad) * math.cos(azimuth_rad),
            math.sin(inclination_rad) * math.sin(azimuth_rad),
            math.cos(inclination_rad),
        ]
    )


def zenith_angles(zenith: np.ndarray) -> tuple[float, float]:
    unit = np.asarray(zenith, dtype=np.float64)
    unit /= np.linalg.norm(unit)
    return (
        math.atan2(float(unit[1]), float(unit[0])),
        math.acos(float(np.clip(unit[2], -1.0, 1.0))),
    )


def apply_refraction(
    vacuum_camera_rays: np.ndarray,
    zenith_camera: np.ndarray,
    refraction_a_arcsec: float,
    refraction_b_arcsec: float,
) -> tuple[np.ndarray, np.ndarray]:
    vacuum = _normalise(vacuum_camera_rays)
    zenith = np.asarray(zenith_camera, dtype=np.float64)
    zenith /= np.linalg.norm(zenith)
    cosine = np.clip(vacuum @ zenith, -1.0, 1.0)
    distance = np.arccos(cosine)
    safe_distance = np.minimum(distance, math.radians(88.5))
    tangent_distance = np.tan(safe_distance)
    displacement = ARCSEC_TO_RAD * (
        refraction_a_arcsec * tangent_distance
        + refraction_b_arcsec * tangent_distance**3
    )
    apparent_distance = np.maximum(distance - displacement, 0.0)
    transverse = vacuum - cosine[:, None] * zenith
    transverse_norm = np.linalg.norm(transverse, axis=1)
    direction = np.divide(
        transverse,
        transverse_norm[:, None],
        out=np.zeros_like(transverse),
        where=transverse_norm[:, None] > 1.0e-12,
    )
    apparent = (
        np.cos(apparent_distance)[:, None] * zenith
        + np.sin(apparent_distance)[:, None] * direction
    )
    at_zenith = transverse_norm <= 1.0e-12
    apparent[at_zenith] = zenith
    valid = distance < math.radians(88.5)
    return _normalise(apparent), valid


def remove_refraction(
    apparent_camera_rays: np.ndarray,
    zenith_camera: np.ndarray,
    refraction_a_arcsec: float,
    refraction_b_arcsec: float,
) -> np.ndarray:
    apparent = _normalise(apparent_camera_rays)
    zenith = np.asarray(zenith_camera, dtype=np.float64)
    zenith /= np.linalg.norm(zenith)
    cosine = np.clip(apparent @ zenith, -1.0, 1.0)
    apparent_distance = np.arccos(cosine)
    vacuum_distance = apparent_distance.copy()
    a = refraction_a_arcsec * ARCSEC_TO_RAD
    b = refraction_b_arcsec * ARCSEC_TO_RAD
    for _ in range(15):
        limited = np.minimum(vacuum_distance, math.radians(88.5))
        tangent = np.tan(limited)
        function = vacuum_distance - a * tangent - b * tangent**3 - apparent_distance
        derivative = (
            1.0
            - a / np.cos(limited) ** 2
            - 3.0 * b * tangent**2 / np.cos(limited) ** 2
        )
        vacuum_distance -= np.divide(
            function,
            derivative,
            out=np.zeros_like(function),
            where=np.abs(derivative) > 1.0e-8,
        )
        vacuum_distance = np.clip(vacuum_distance, 0.0, math.radians(89.0))
    transverse = apparent - cosine[:, None] * zenith
    transverse_norm = np.linalg.norm(transverse, axis=1)
    direction = np.divide(
        transverse,
        transverse_norm[:, None],
        out=np.zeros_like(transverse),
        where=transverse_norm[:, None] > 1.0e-12,
    )
    vacuum = (
        np.cos(vacuum_distance)[:, None] * zenith
        + np.sin(vacuum_distance)[:, None] * direction
    )
    vacuum[transverse_norm <= 1.0e-12] = zenith
    return _normalise(vacuum)


def _angular_residual(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    return np.arccos(np.clip(np.sum(first * second, axis=1), -1.0, 1.0))


def fit_atmospheric_refraction(
    apparent_camera_rays: np.ndarray,
    target_icrs_rays: np.ndarray,
    initial_rotation_camera_to_icrs: np.ndarray,
) -> AtmosphericRefractionFit:
    observed = _normalise(apparent_camera_rays)
    target = _normalise(target_icrs_rays)
    if observed.shape != target.shape or observed.shape[0] < 12:
        raise ValueError("At least twelve matched rays are required for refraction fitting.")

    def vacuum_for_rotation(delta: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        rotation = (
            Rotation.from_rotvec(delta).as_matrix()
            @ initial_rotation_camera_to_icrs
        )
        return (rotation.T @ target.T).T, rotation

    baseline_fit = least_squares(
        lambda delta: (vacuum_for_rotation(delta)[0] - observed).ravel(),
        np.zeros(3),
        loss="soft_l1",
        f_scale=math.radians(1.0 / 60.0),
        max_nfev=1000,
    )
    baseline_vacuum, baseline_rotation = vacuum_for_rotation(baseline_fit.x)
    baseline_angles = _angular_residual(baseline_vacuum, observed)
    baseline_rss = max(float(np.sum(baseline_angles**2)), 1.0e-30)

    mean_direction = np.sum(observed, axis=0)
    mean_direction /= np.linalg.norm(mean_direction)
    seeds = [mean_direction, np.array([0.0, 0.0, 1.0])]
    for direction in (
        np.array([1.0, 0.0, 0.0]),
        np.array([-1.0, 0.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
        np.array([0.0, -1.0, 0.0]),
    ):
        candidate = mean_direction + 0.65 * direction
        candidate /= np.linalg.norm(candidate)
        seeds.append(candidate)

    lower = np.array(
        [
            -math.radians(2.0),
            -math.radians(2.0),
            -math.radians(2.0),
            -math.pi,
            0.0,
            0.0,
            -2.0,
        ]
    )
    upper = np.array(
        [
            math.radians(2.0),
            math.radians(2.0),
            math.radians(2.0),
            math.pi,
            math.pi,
            180.0,
            2.0,
        ]
    )
    best_fit = None
    best_rss = float("inf")
    best_angles = None
    best_zenith = None
    best_rotation = baseline_rotation
    for seed in seeds:
        azimuth, inclination = zenith_angles(seed)
        initial = np.array(
            [
                *baseline_fit.x,
                azimuth,
                inclination,
                45.0,
                0.0,
            ]
        )

        def residual(parameters: np.ndarray) -> np.ndarray:
            vacuum, _ = vacuum_for_rotation(parameters[:3])
            zenith = zenith_from_angles(parameters[3], parameters[4])
            predicted, valid = apply_refraction(
                vacuum,
                zenith,
                parameters[5],
                parameters[6],
            )
            vector = (predicted - observed).ravel()
            zenith_distance = np.arccos(np.clip(vacuum @ zenith, -1.0, 1.0))
            horizon_penalty = np.maximum(
                zenith_distance - math.radians(88.0), 0.0
            )
            return np.concatenate((vector, 10.0 * horizon_penalty, (~valid).astype(float)))

        fitted = least_squares(
            residual,
            initial,
            bounds=(lower, upper),
            loss="soft_l1",
            f_scale=math.radians(1.0 / 60.0),
            max_nfev=2000,
        )
        vacuum, rotation = vacuum_for_rotation(fitted.x[:3])
        zenith = zenith_from_angles(fitted.x[3], fitted.x[4])
        predicted, _ = apply_refraction(vacuum, zenith, fitted.x[5], fitted.x[6])
        angles = _angular_residual(predicted, observed)
        rss = max(float(np.sum(angles**2)), 1.0e-30)
        if rss < best_rss:
            best_fit = fitted
            best_rss = rss
            best_angles = angles
            best_zenith = zenith
            best_rotation = rotation

    assert best_fit is not None and best_angles is not None and best_zenith is not None
    vacuum = (best_rotation.T @ target.T).T
    zenith_distance = np.degrees(
        np.arccos(np.clip(vacuum @ best_zenith, -1.0, 1.0))
    )
    n = observed.shape[0]
    baseline_bic = n * math.log(baseline_rss / n) + 3.0 * math.log(n)
    fitted_bic = n * math.log(best_rss / n) + 7.0 * math.log(n)
    delta_bic = baseline_bic - fitted_bic
    sigma_a = None
    try:
        covariance = np.linalg.inv(best_fit.jac.T @ best_fit.jac)
        variance = 2.0 * best_fit.cost / max(best_fit.fun.size - best_fit.x.size, 1)
        sigma_a = float(math.sqrt(max(covariance[5, 5] * variance, 0.0)))
    except np.linalg.LinAlgError:
        pass
    boundary_limited = bool(
        best_fit.x[5] <= 0.01
        or best_fit.x[5] >= 179.99
        or abs(best_fit.x[6]) >= 1.99
        or np.max(zenith_distance) >= 87.9
    )
    altitude_span = float(np.ptp(zenith_distance))
    significant = (
        delta_bic >= 10.0
        and not boundary_limited
        and altitude_span >= 20.0
        and (
            sigma_a is None
            or best_fit.x[5] >= max(1.0, 3.0 * sigma_a)
        )
    )
    if altitude_span < 20.0 or boundary_limited:
        status = "not_identifiable"
    elif significant:
        status = "detected"
    else:
        status = "no_significant_refraction"
    corrected = remove_refraction(
        observed,
        best_zenith,
        float(best_fit.x[5]),
        float(best_fit.x[6]),
    )
    return AtmosphericRefractionFit(
        status=status,
        zenith_camera=best_zenith,
        refraction_a_arcsec=float(best_fit.x[5]),
        refraction_b_arcsec=float(best_fit.x[6]),
        rotation_camera_to_icrs=best_rotation,
        corrected_camera_rays=corrected,
        baseline_rms_arcmin=math.degrees(
            math.sqrt(float(np.mean(baseline_angles**2)))
        )
        * 60.0,
        fitted_rms_arcmin=math.degrees(
            math.sqrt(float(np.mean(best_angles**2)))
        )
        * 60.0,
        delta_bic=delta_bic,
        zenith_distance_range_deg=(
            float(np.min(zenith_distance)),
            float(np.max(zenith_distance)),
        ),
        refraction_a_sigma_arcsec=sigma_a,
        boundary_limited=boundary_limited,
    )
