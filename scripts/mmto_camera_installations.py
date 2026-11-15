"""Compatibility facade for MMTO source-to-installation assignments.

New code belongs in :mod:`v24.visible_sky_registry`.  These public names remain
for the preserved MMTO pipeline and existing callers.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from v24.visible_sky_registry import (
    assign_source_to_manifest as _assign_source_to_manifest,
    assignment_for_source as _generic_assignment_for_source,
    validate_source_against_manifest as _validate_source_against_manifest,
)


ORIENTATION = "detector_native_top_left_xy_right_y_down"
SOURCE_ID = "mmto"
CAMERA_ID = "mmto-skycam"


@dataclass(frozen=True, slots=True)
class CameraAssignment:
    source_sha256: str
    installation_id: str
    mask_id: str
    mask_sha256: str
    manifest_path: Path
    manifest_sha256: str
    instrument: str
    detector_shape: tuple[int, int]
    plane_layout: str
    orientation: str

    def as_record(self) -> dict[str, object]:
        return {
            "schema": "mmto-camera-installation-assignment-v1",
            "source_sha256": self.source_sha256,
            "installation_id": self.installation_id,
            "mask_id": self.mask_id,
            "mask_sha256": self.mask_sha256,
            "manifest_path": str(self.manifest_path),
            "manifest_sha256": self.manifest_sha256,
            "instrument": self.instrument,
            "detector_shape": list(self.detector_shape),
            "plane_layout": self.plane_layout,
            "orientation": self.orientation,
            "assignment_basis": "operator-selected active installation; validated FITS identity, detector geometry, and approved mask",
        }


def validate_assignment(source: Path, source_sha256: str, manifest_path: Path,
                        installation_id: str) -> CameraAssignment:
    record = _validate_source_against_manifest(
        source,
        source_sha256,
        manifest_path,
        installation_id,
        source_id=SOURCE_ID,
        camera_id=CAMERA_ID,
        orientation=ORIENTATION,
    )
    return CameraAssignment(
        source_sha256=source_sha256,
        installation_id=installation_id,
        mask_id=str(record["mask_id"]),
        mask_sha256=str(record["mask_sha256"]),
        manifest_path=Path(str(record["manifest_path"])),
        manifest_sha256=str(record["manifest_sha256"]),
        instrument=str(record["instrument"]),
        detector_shape=tuple(int(value) for value in record["detector_shape"]),
        plane_layout=str(record["plane_layout"]),
        orientation=ORIENTATION,
    )


def assignment_for_source(registry_path: Path, source_sha256: str) -> dict[str, object] | None:
    return _generic_assignment_for_source(registry_path, source_sha256)


def assign_source(registry_path: Path, source: Path, source_sha256: str,
                  manifest_path: Path, installation_id: str) -> dict[str, object]:
    """Validate and append one immutable source assignment, idempotently."""
    return _assign_source_to_manifest(
        registry_path,
        source,
        source_sha256,
        manifest_path,
        installation_id,
        source_id=SOURCE_ID,
        camera_id=CAMERA_ID,
        orientation=ORIENTATION,
    )
