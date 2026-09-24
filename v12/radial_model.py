"""Nested radius-dependent extensions of the Barghini point-star camera."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from barghini_model import (
    BarghiniParameters,
    _horizontal_to_projection,
    _projection_to_horizontal,
    extended_radial_du_dr,
    extended_radial_u,
    inverse_extended_radial_u,
    wrap_azimuth,
)
from point_star_barghini import BarghiniCamera


@dataclass(frozen=True)
class ModelValidation:
    valid: bool
    reason: str | None
    minimum_derivative: float | None
    endpoint_angle_rad: float | None

    def __bool__(self) -> bool:
        return self.valid

    def serialise(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class ExtendedBarghiniCamera:
    """Barghini camera with nested angular rho^3 through rho^11 terms."""

    shape: tuple[int, int]
    reference_rotation: np.ndarray
    p: np.ndarray
    coefficients: np.ndarray
    detector_parity: int = 1

    def __post_init__(self) -> None:
        self.shape = tuple(int(value) for value in self.shape)
        self.reference_rotation = np.asarray(self.reference_rotation, dtype=float)
        self.p = np.asarray(self.p, dtype=float)
        self.coefficients = np.asarray(self.coefficients, dtype=float)
        if self.detector_parity not in (-1, 1):
            raise ValueError("detector parity must be +1 (normal) or -1 (mirrored)")
        if self.p.shape != (8,):
            raise ValueError("normalised Barghini parameter vector must have length 8")
        if self.coefficients.ndim != 1 or self.coefficients.size > 5:
            raise ValueError("radial coefficients must be a vector of zero to five values")

    @property
    def scale(self) -> float:
        return float(np.linalg.norm(self.shape) / 2.0)

    @property
    def physical(self) -> BarghiniParameters:
        p = self.p
        scale = self.scale
        return BarghiniParameters(
            p[0],
            *list(p[1:5] * scale),
            np.exp(p[5]) / scale,
            p[6],
            p[7] / scale,
        )

    @property
    def corner_radius(self) -> float:
        h, w = self.shape
        q = self.physical
        corners = np.array([[0.0, 0.0], [w - 1.0, 0.0], [0.0, h - 1.0], [w - 1.0, h - 1.0]])
        return float(np.max(np.linalg.norm(corners - [q.x_o, q.y_o], axis=1)))

    @classmethod
    def from_camera(
        cls,
        camera: BarghiniCamera,
        coefficients: np.ndarray | list[float] | tuple[float, ...] = (),
    ) -> "ExtendedBarghiniCamera":
        return cls(
            camera.shape,
            np.array(camera.reference_rotation, copy=True),
            np.array(camera.p, copy=True),
            np.asarray(coefficients, dtype=float),
            camera.detector_parity,
        )

    @classmethod
    def from_serialised(cls, record: dict[str, object]) -> "ExtendedBarghiniCamera":
        parity_name = record.get("detector_parity", "normal")
        if parity_name not in ("normal", "mirrored"):
            raise ValueError(f"Unknown detector parity: {parity_name!r}")
        extension = record.get("radial_extension", {})
        return cls(
            tuple(record["shape"]),
            np.asarray(record["reference_rotation"], dtype=float),
            np.asarray(record["normalised_parameters"], dtype=float),
            np.asarray(extension.get("coefficients_rad", []), dtype=float),
            1 if parity_name == "normal" else -1,
        )

    def _derived_axis(self) -> tuple[float, float]:
        q = self.physical
        dx = q.x_o - q.x_z
        dy = q.y_o - q.y_z
        radius = float(np.hypot(dx, dy))
        e = float(wrap_azimuth(q.a0 + np.arctan2(dy, dx)))
        epsilon = float(extended_radial_u(radius, q, self.scale, self.coefficients))
        return e, epsilon

    def radial_derivative_grid(self, count: int = 1025) -> tuple[np.ndarray, np.ndarray]:
        radius = np.linspace(0.0, self.corner_radius, count)
        derivative = extended_radial_du_dr(
            radius, self.physical, self.scale, self.coefficients
        )
        return radius, derivative

    def is_valid(self, radius_limit_px: float | None = None) -> ModelValidation:
        """Validate monotonicity on the detector and uniqueness on an active radius.

        With no limit this retains the conservative full-rectangle check used in
        serialisation.  Fits may supply the largest measured radius so unused
        black corners outside the lens circle do not invalidate observed data.
        """
        if not np.all(np.isfinite(self.coefficients)):
            return ModelValidation(False, "non_finite_coefficients", None, None)
        _, derivative = self.radial_derivative_grid()
        finite_derivative = derivative[np.isfinite(derivative)]
        minimum = float(np.min(finite_derivative)) if finite_derivative.size else None
        if finite_derivative.size != derivative.size or minimum is None or minimum <= 0.0:
            return ModelValidation(False, "non_monotonic", minimum, None)
        radius_limit = self.corner_radius if radius_limit_px is None else float(radius_limit_px)
        if (
            not np.isfinite(radius_limit)
            or radius_limit < 0.0
            or radius_limit > self.corner_radius + 1.0e-9
        ):
            return ModelValidation(False, "invalid_radius_limit", minimum, None)
        endpoint = float(
            extended_radial_u(
                radius_limit, self.physical, self.scale, self.coefficients
            )
        )
        if not np.isfinite(endpoint) or endpoint < 0.0 or endpoint >= np.pi:
            return ModelValidation(False, "inverse_domain", minimum, endpoint)
        return ModelValidation(True, None, minimum, endpoint)

    def to_sky(self, xy: np.ndarray | list[list[float]]) -> np.ndarray:
        points = np.asarray(xy, dtype=float)
        q = self.physical
        dx = points[:, 0] - q.x_o
        dy = points[:, 1] - q.y_o
        radius = np.hypot(dx, dy)
        e, epsilon = self._derived_axis()
        b = q.a0 - e + np.arctan2(dy, dx)
        u = extended_radial_u(radius, q, self.scale, self.coefficients)
        a, z = _projection_to_horizontal(b, u, e, epsilon)
        ray = np.c_[np.sin(z) * np.cos(a), np.sin(z) * np.sin(a), np.cos(z)]
        ray[:, 1] *= self.detector_parity
        return ray @ self.reference_rotation.T

    def project(self, sky: np.ndarray | list[list[float]]) -> np.ndarray:
        if not np.all(np.isfinite(self.coefficients)):
            raise ValueError("invalid radial model: non_finite_coefficients")
        _, derivative = self.radial_derivative_grid()
        if not np.all(np.isfinite(derivative)) or np.any(derivative <= 0.0):
            raise ValueError("invalid radial model: non_monotonic")
        ray = np.asarray(sky, dtype=float) @ self.reference_rotation
        ray[:, 1] *= self.detector_parity
        azimuth = np.arctan2(ray[:, 1], ray[:, 0])
        zenith_distance = np.arctan2(np.linalg.norm(ray[:, :2], axis=1), ray[:, 2])
        e, epsilon = self._derived_axis()
        b, u = _horizontal_to_projection(azimuth, zenith_distance, e, epsilon)
        radius = inverse_extended_radial_u(
            u,
            self.physical,
            self.scale,
            self.coefficients,
            self.corner_radius,
        )
        detector_angle = b - self.physical.a0 + e
        return np.c_[
            self.physical.x_o + radius * np.cos(detector_angle),
            self.physical.y_o + radius * np.sin(detector_angle),
        ]

    def serialise(self) -> dict[str, object]:
        validation = self.is_valid()
        return {
            "model": "Barghini_2019_equations_5_6_11_nested_radial",
            "parameters": asdict(self.physical),
            "normalised_parameters": self.p.tolist(),
            "reference_rotation": self.reference_rotation.tolist(),
            "shape": list(self.shape),
            "detector_parity": "normal" if self.detector_parity == 1 else "mirrored",
            "reference_Z": "fixed celestial direction from current blind bootstrap; not local zenith",
            "radial_extension": {
                "powers": list(range(3, 2 * self.coefficients.size + 2, 2)),
                "coefficients_rad": self.coefficients.tolist(),
                "coefficient_units": "radian",
                "normalised_radius": "r / scale_px",
                "scale_px": self.scale,
            },
            "radial_validation": validation.serialise(),
            "monotonic_on_detector": bool(validation.valid),
        }
