"""Append-only MMTO source-to-camera-installation assignments."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re

from astropy.io import fits

from v24.point_star_visible_sky import VisibleSkyMask


ORIENTATION = "detector_native_top_left_xy_right_y_down"
_SHA256 = re.compile(r"[0-9a-f]{64}")


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


def _source_layout(path: Path) -> tuple[str, tuple[int, int], str]:
    try:
        with fits.open(path, memmap=False, do_not_scale_image_data=True) as hdus:
            header = hdus[0].header
            instrument = str(header.get("INSTRUME", "")).strip()
            naxis = int(header.get("NAXIS", 0))
            axes = tuple(int(header.get(f"NAXIS{index}", 0)) for index in range(1, naxis + 1))
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError(f"cannot validate MMTO installation from FITS header: {exc}") from exc
    if naxis == 3 and len(axes) == 3 and axes[2] in (3, 4):
        shape, layout = (axes[1], axes[0]), "plane_first"
    elif naxis == 3 and len(axes) == 3 and axes[0] in (3, 4):
        shape, layout = (axes[2], axes[1]), "plane_last"
    else:
        raise ValueError(f"unsupported MMTO detector layout: NAXIS={naxis}, axes={axes}")
    return instrument, shape, layout


def validate_assignment(source: Path, source_sha256: str, manifest_path: Path,
                        installation_id: str) -> CameraAssignment:
    source = Path(source).resolve(strict=True)
    manifest_path = Path(manifest_path).resolve(strict=True)
    if _SHA256.fullmatch(source_sha256) is None:
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    with source.open("rb") as stream:
        observed = hashlib.file_digest(stream, "sha256").hexdigest()
    if observed != source_sha256:
        raise ValueError("camera-installation assignment source checksum mismatch")
    instrument, detector_shape, layout = _source_layout(source)
    mask = VisibleSkyMask.load(
        manifest_path,
        installation_id=installation_id,
        instrument=instrument,
        detector_shape=detector_shape,
        plane_layout=layout,
        orientation=ORIENTATION,
    )
    return CameraAssignment(
        source_sha256=source_sha256,
        installation_id=installation_id,
        mask_id=str(mask.mask_id),
        mask_sha256=str(mask.mask_sha256),
        manifest_path=manifest_path,
        manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        instrument=instrument,
        detector_shape=detector_shape,
        plane_layout=layout,
        orientation=ORIENTATION,
    )


def _records(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    if not path.is_file():
        raise ValueError(f"camera assignment registry is not a regular file: {path}")
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid camera assignment record at line {number}") from exc
        if row.get("schema") != "mmto-camera-installation-assignment-v1":
            raise ValueError(f"unsupported camera assignment record at line {number}")
        rows.append(row)
    return rows


def assignment_for_source(registry_path: Path, source_sha256: str) -> dict[str, object] | None:
    matches = [row for row in _records(Path(registry_path))
               if row.get("source_sha256") == source_sha256]
    if len(matches) > 1 and any(row != matches[0] for row in matches[1:]):
        raise ValueError("conflicting camera-installation assignments")
    return None if not matches else matches[0]


def assign_source(registry_path: Path, source: Path, source_sha256: str,
                  manifest_path: Path, installation_id: str) -> dict[str, object]:
    """Validate and append one immutable source assignment, idempotently."""
    assignment = validate_assignment(
        source, source_sha256, manifest_path, installation_id)
    record = assignment.as_record()
    registry_path = Path(registry_path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(registry_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        with os.fdopen(descriptor, "r+", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            existing = []
            stream.seek(0)
            for line in stream:
                if line.strip():
                    existing.append(json.loads(line))
            matches = [row for row in existing
                       if row.get("source_sha256") == source_sha256]
            if matches:
                comparable = {key: value for key, value in matches[0].items()
                              if key != "recorded_utc"}
                if comparable != record:
                    raise ValueError("conflicting camera-installation reassignment")
                return matches[0]
            record["recorded_utc"] = datetime.now(timezone.utc).isoformat()
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            return record
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
