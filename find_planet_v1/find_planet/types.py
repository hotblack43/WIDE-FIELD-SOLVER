"""Immutable value objects shared by the find-planet stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class SelectedCentroid:
    run_id: str
    source_sha256: str
    source_path: str
    night: str
    observation_time_utc: str
    detection_id: str
    x_px: float
    y_px: float
    stellar_fit_rms_arcmin: float
    source_class: str
    saturated: bool


@dataclass(frozen=True)
class CameraReceipt:
    run_id: str
    source_sha256: str
    source_path: str
    solver_version: str
    camera: Mapping[str, Any]


@dataclass(frozen=True)
class AnonymousDirection:
    object_id: str
    run_id: str
    source_sha256: str
    source_path: str
    night: str
    observation_time_utc: str
    detection_id: str
    x_px: float
    y_px: float
    icrs_unit: tuple[float, float, float]
    stellar_fit_rms_arcmin: float
    source_class: str
    saturated: bool
    integrated_refraction_status: str


@dataclass(frozen=True)
class ObserverState:
    jd_tdb: float
    position_au: tuple[float, float, float]
    velocity_au_per_day: tuple[float, float, float]
    earth_position_au: tuple[float, float, float]
    earth_velocity_au_per_day: tuple[float, float, float]
    topocentre_position_au: tuple[float, float, float]
    topocentre_velocity_au_per_day: tuple[float, float, float]


@dataclass(frozen=True)
class Observation:
    direction: AnonymousDirection
    jd_tdb: float
    measured_unit: tuple[float, float, float]
    sigma_arcmin: float
    observer: ObserverState


@dataclass(frozen=True)
class HeliocentricState:
    reference_jd_tdb: float
    position_au: tuple[float, float, float]
    velocity_au_per_day: tuple[float, float, float]


@dataclass(frozen=True)
class OrbitalElements:
    reference_jd_tdb: float
    semimajor_axis_au: float
    eccentricity: float
    inclination_deg: float
    longitude_ascending_node_deg: float | None
    argument_perihelion_deg: float | None
    mean_anomaly_deg: float | None
    singular_flags: tuple[str, ...]


@dataclass(frozen=True)
class RangeSeedAudit:
    distance_au: float
    range_rate_au_per_day: float | None
    status: str
    reason: str
    state: HeliocentricState | None


@dataclass(frozen=True)
class ObservationFit:
    run_id: str
    east_arcmin: float
    north_arcmin: float
    norm_arcmin: float
    sigma_arcmin: float
    robust_weight: float
    status: str
    reason: str


@dataclass(frozen=True)
class FitSeedAudit:
    seed_index: int
    status: str
    reason: str
    cost: float | None


@dataclass(frozen=True)
class OrbitSolution:
    state: HeliocentricState
    elements: OrbitalElements
    cost: float
    success: bool
    observation_fits: tuple[ObservationFit, ...]
    seed_index: int


@dataclass(frozen=True)
class OrbitFitResult:
    reference_jd_tdb: float
    solutions: tuple[OrbitSolution, ...]
    seed_audit: tuple[FitSeedAudit, ...]
