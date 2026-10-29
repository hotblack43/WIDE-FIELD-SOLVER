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
