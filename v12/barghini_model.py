"""Barghini et al. (2019) all-sky astrometric projection.

Angles are radians and detector coordinates are pixels throughout this module.
The default model uses the paper's reparameterisation in which the optical
centre O and detector position of the astronomical zenith Z are independent.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq
from scipy.special import lambertw

TWO_PI = 2.0 * np.pi


def wrap_azimuth(angle: np.ndarray | float) -> np.ndarray:
    """Wrap an angle to [0, 2*pi)."""
    return np.mod(np.asarray(angle, dtype=float), TWO_PI)


def wrap_signed(angle: np.ndarray | float) -> np.ndarray:
    """Wrap an angular difference to [-pi, pi)."""
    return (np.asarray(angle, dtype=float) + np.pi) % TWO_PI - np.pi


def radial_u(r: np.ndarray | float, v: float, s: float, d: float) -> np.ndarray:
    """Borovicka fish-eye transform u(r) = V*r + S*expm1(D*r)."""
    radius = np.asarray(r, dtype=float)
    return v * radius + s * np.expm1(d * radius)


def radial_du_dr(r: np.ndarray | float, v: float, s: float, d: float) -> np.ndarray:
    """Derivative of the radial transform, used to check invertibility."""
    radius = np.asarray(r, dtype=float)
    return v + s * d * np.exp(d * radius)


def extended_radial_u(
    r: np.ndarray | float,
    parameters: "BarghiniParameters",
    scale: float,
    coefficients: np.ndarray | list[float] | tuple[float, ...],
) -> np.ndarray:
    """Nested Barghini radius with angular rho^3, rho^5, ... terms."""
    radius = np.asarray(r, dtype=float)
    coefficient_array = np.asarray(coefficients, dtype=float)
    baseline = radial_u(radius, parameters.v, parameters.s, parameters.d)
    if coefficient_array.size == 0:
        return baseline
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("radial scale must be positive and finite")
    rho = radius / scale
    powers = 2 * np.arange(1, coefficient_array.size + 1) + 1
    correction = np.sum(
        coefficient_array * rho[..., None] ** powers,
        axis=-1,
    )
    return baseline + correction


def extended_radial_du_dr(
    r: np.ndarray | float,
    parameters: "BarghiniParameters",
    scale: float,
    coefficients: np.ndarray | list[float] | tuple[float, ...],
) -> np.ndarray:
    """Derivative of :func:`extended_radial_u` with respect to pixels."""
    radius = np.asarray(r, dtype=float)
    coefficient_array = np.asarray(coefficients, dtype=float)
    baseline = radial_du_dr(radius, parameters.v, parameters.s, parameters.d)
    if coefficient_array.size == 0:
        return baseline
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("radial scale must be positive and finite")
    rho = radius / scale
    powers = 2 * np.arange(1, coefficient_array.size + 1) + 1
    correction = np.sum(
        coefficient_array * powers * rho[..., None] ** (powers - 1) / scale,
        axis=-1,
    )
    return baseline + correction


def inverse_extended_radial_u(
    u: np.ndarray | float,
    parameters: "BarghiniParameters",
    scale: float,
    coefficients: np.ndarray | list[float] | tuple[float, ...],
    corner_radius: float,
) -> np.ndarray:
    """Invert a validated extended mapping within the detector-corner domain."""
    values = np.asarray(u, dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values < -1.0e-12):
        raise ValueError("inverse_domain: u must be finite and non-negative")
    grid = np.linspace(0.0, float(corner_radius), 1025)
    derivative = extended_radial_du_dr(grid, parameters, scale, coefficients)
    if not np.all(np.isfinite(derivative)) or np.any(derivative <= 0.0):
        raise ValueError("non_monotonic: radial derivative is not positive")
    upper_u = float(
        extended_radial_u(corner_radius, parameters, scale, coefficients)
    )
    if not np.isfinite(upper_u) or upper_u <= 0.0:
        raise ValueError("inverse_domain: radial endpoint is invalid")

    def invert_one(value: float) -> float:
        if value <= 1.0e-15:
            return 0.0
        if value > upper_u + 1.0e-12:
            raise ValueError(
                f"inverse_domain: angle {value} exceeds detector endpoint {upper_u}"
            )
        return float(
            brentq(
                lambda radius: float(
                    extended_radial_u(radius, parameters, scale, coefficients)
                )
                - value,
                0.0,
                float(corner_radius),
                xtol=1.0e-12,
                rtol=1.0e-14,
            )
        )

    flat = np.fromiter(
        (invert_one(float(value)) for value in values.flat),
        dtype=float,
        count=values.size,
    )
    return flat.reshape(values.shape)


def _inverse_radial_scalar(u: float, v: float, s: float, d: float) -> float:
    if u < -1.0e-12:
        raise ValueError("u must be non-negative")
    if abs(u) <= 1.0e-15:
        return 0.0
    if v <= 0.0:
        raise ValueError("V must be positive")
    if abs(s) <= 1.0e-15 or abs(d) <= 1.0e-12:
        slope = v + s * d
        if slope <= 0.0:
            raise ValueError("radial transform is not increasing at the origin")
        return u / slope

    shifted = u + s
    argument = (d * s / v) * np.exp(d * shifted / v)
    candidate = shifted / v - lambertw(argument, k=0).real / d
    if (
        np.isfinite(candidate)
        and candidate >= 0.0
        and radial_du_dr(candidate, v, s, d) > 0.0
        and abs(float(radial_u(candidate, v, s, d)) - u) < 1.0e-9
    ):
        return float(candidate)

    upper = max(u / v, 1.0)
    while float(radial_u(upper, v, s, d)) < u and upper < 1.0e7:
        upper *= 2.0
    if radial_du_dr(np.array([0.0, upper]), v, s, d).min() <= 0.0:
        raise ValueError("radial transform is not monotonic on the inversion interval")
    return float(
        brentq(lambda radius: float(radial_u(radius, v, s, d)) - u, 0.0, upper)
    )


def inverse_radial_u(u: np.ndarray | float, v: float, s: float, d: float) -> np.ndarray:
    """Invert the radial transform using Lambert W with a numerical fallback."""
    values = np.asarray(u, dtype=float)
    flat = np.fromiter(
        (_inverse_radial_scalar(float(value), v, s, d) for value in values.flat),
        dtype=float,
        count=values.size,
    )
    return flat.reshape(values.shape)


@dataclass(frozen=True)
class BarghiniParameters:
    """Eight parameters of the O/Z form of the Barghini model."""

    a0: float
    x_o: float
    y_o: float
    x_z: float
    y_z: float
    v: float
    s: float
    d: float

    def as_array(self) -> np.ndarray:
        return np.array(
            [self.a0, self.x_o, self.y_o, self.x_z, self.y_z, self.v, self.s, self.d],
            dtype=float,
        )

    @classmethod
    def from_array(cls, values: np.ndarray) -> BarghiniParameters:
        return cls(*np.asarray(values, dtype=float).tolist())

    def derived_axis(self) -> tuple[float, float]:
        """Return optical-axis azimuth E and zenith distance epsilon."""
        dx = self.x_o - self.x_z
        dy = self.y_o - self.y_z
        r_epsilon = float(np.hypot(dx, dy))
        e = float(wrap_azimuth(self.a0 + np.arctan2(dy, dx)))
        epsilon = float(radial_u(r_epsilon, self.v, self.s, self.d))
        return e, epsilon


@dataclass(frozen=True)
class DirectParameters:
    """Original correlated O/E/epsilon form of the eight-parameter model."""

    a0: float
    x_o: float
    y_o: float
    e: float
    epsilon: float
    v: float
    s: float
    d: float

    def as_array(self) -> np.ndarray:
        return np.array(
            [self.a0, self.x_o, self.y_o, self.e, self.epsilon, self.v, self.s, self.d],
            dtype=float,
        )

    @classmethod
    def from_array(cls, values: np.ndarray) -> DirectParameters:
        return cls(*np.asarray(values, dtype=float).tolist())


@dataclass(frozen=True)
class CoarseParameters:
    """Five-parameter association projection from equation (8)."""

    a0: float
    x_c: float
    y_c: float
    f: float
    r_scale: float

    def as_array(self) -> np.ndarray:
        return np.array(
            [self.a0, self.x_c, self.y_c, self.f, self.r_scale], dtype=float
        )

    @classmethod
    def from_array(cls, values: np.ndarray) -> CoarseParameters:
        return cls(*np.asarray(values, dtype=float).tolist())


def _projection_to_horizontal(
    b: np.ndarray, u: np.ndarray, e: float, epsilon: float
) -> tuple[np.ndarray, np.ndarray]:
    numerator = np.sin(b) * np.sin(u)
    denominator = np.cos(b) * np.sin(u) * np.cos(epsilon) + np.cos(u) * np.sin(epsilon)
    azimuth = wrap_azimuth(e + np.arctan2(numerator, denominator))
    cos_z = np.cos(u) * np.cos(epsilon) - np.cos(b) * np.sin(u) * np.sin(epsilon)
    zenith_distance = np.arccos(np.clip(cos_z, -1.0, 1.0))
    return azimuth, zenith_distance


def _horizontal_to_projection(
    azimuth: np.ndarray, zenith_distance: np.ndarray, e: float, epsilon: float
) -> tuple[np.ndarray, np.ndarray]:
    delta_a = wrap_signed(azimuth - e)
    x_horizontal = np.sin(zenith_distance) * np.cos(delta_a)
    y_horizontal = np.sin(zenith_distance) * np.sin(delta_a)
    z_horizontal = np.cos(zenith_distance)
    x_projection = x_horizontal * np.cos(epsilon) - z_horizontal * np.sin(epsilon)
    y_projection = y_horizontal
    z_projection = x_horizontal * np.sin(epsilon) + z_horizontal * np.cos(epsilon)
    b = np.arctan2(y_projection, x_projection)
    u = np.arccos(np.clip(z_projection, -1.0, 1.0))
    return b, u


def detector_to_horizontal(
    x: np.ndarray | float,
    y: np.ndarray | float,
    parameters: BarghiniParameters,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply equations (5), (6), and (11) from detector to horizontal sky."""
    x_array, y_array = np.broadcast_arrays(
        np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    )
    dx = x_array - parameters.x_o
    dy = y_array - parameters.y_o
    r = np.hypot(dx, dy)
    e, epsilon = parameters.derived_axis()
    b = parameters.a0 - e + np.arctan2(dy, dx)
    u = radial_u(r, parameters.v, parameters.s, parameters.d)
    return _projection_to_horizontal(b, u, e, epsilon)


def horizontal_to_detector(
    azimuth: np.ndarray | float,
    zenith_distance: np.ndarray | float,
    parameters: BarghiniParameters,
) -> tuple[np.ndarray, np.ndarray]:
    """Invert the O/Z Barghini mapping from horizontal sky to detector."""
    azimuth_array, zenith_array = np.broadcast_arrays(
        np.asarray(azimuth, dtype=float), np.asarray(zenith_distance, dtype=float)
    )
    e, epsilon = parameters.derived_axis()
    b, u = _horizontal_to_projection(azimuth_array, zenith_array, e, epsilon)
    r = inverse_radial_u(u, parameters.v, parameters.s, parameters.d)
    detector_angle = b - parameters.a0 + e
    x = parameters.x_o + r * np.cos(detector_angle)
    y = parameters.y_o + r * np.sin(detector_angle)
    return x, y


def detector_to_horizontal_direct(
    x: np.ndarray | float,
    y: np.ndarray | float,
    parameters: DirectParameters,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply the original O/E/epsilon parameterisation for comparison tests."""
    x_array, y_array = np.broadcast_arrays(
        np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    )
    dx = x_array - parameters.x_o
    dy = y_array - parameters.y_o
    b = parameters.a0 - parameters.e + np.arctan2(dy, dx)
    u = radial_u(np.hypot(dx, dy), parameters.v, parameters.s, parameters.d)
    return _projection_to_horizontal(b, u, parameters.e, parameters.epsilon)


def coarse_detector_to_horizontal(
    x: np.ndarray | float,
    y: np.ndarray | float,
    parameters: CoarseParameters,
) -> tuple[np.ndarray, np.ndarray]:
    """Equation (8), with clipping only at numerical round-off."""
    x_array, y_array = np.broadcast_arrays(
        np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    )
    dx = x_array - parameters.x_c
    dy = y_array - parameters.y_c
    ratio = np.hypot(dx, dy) / parameters.r_scale
    azimuth = wrap_azimuth(parameters.a0 + np.arctan2(dy, dx))
    zenith_distance = parameters.f * np.arcsin(np.clip(ratio, -1.0, 1.0))
    return azimuth, zenith_distance


def coarse_horizontal_to_detector(
    azimuth: np.ndarray | float,
    zenith_distance: np.ndarray | float,
    parameters: CoarseParameters,
) -> tuple[np.ndarray, np.ndarray]:
    """Analytic inverse of equation (8), used for catalogue association."""
    azimuth_array, zenith_array = np.broadcast_arrays(
        np.asarray(azimuth, dtype=float), np.asarray(zenith_distance, dtype=float)
    )
    r = parameters.r_scale * np.sin(zenith_array / parameters.f)
    detector_angle = azimuth_array - parameters.a0
    x = parameters.x_c + r * np.cos(detector_angle)
    y = parameters.y_c + r * np.sin(detector_angle)
    return x, y


def horizontal_residuals(
    predicted_azimuth: np.ndarray,
    predicted_zenith_distance: np.ndarray,
    catalogue_azimuth: np.ndarray,
    catalogue_zenith_distance: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Paper residuals: wrapped delta-azimuth*sin(z_cat) and delta-z."""
    delta_azimuth = wrap_signed(predicted_azimuth - catalogue_azimuth)
    return (
        delta_azimuth * np.sin(catalogue_zenith_distance),
        predicted_zenith_distance - catalogue_zenith_distance,
    )
