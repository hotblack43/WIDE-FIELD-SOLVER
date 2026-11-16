"""Append-only layered registry for approved visible-sky calibrations."""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from typing import IO, Sequence

if __package__:
    from .point_star_image import load_scientific_image
    from .point_star_visible_sky import VisibleSkyMask
    from .visible_sky_automatic import validate_automatic_acceptance
else:
    from point_star_image import load_scientific_image
    from point_star_visible_sky import VisibleSkyMask
    from visible_sky_automatic import validate_automatic_acceptance


REGISTRY_SCHEMA = "wide-field-solver-calibration-registry-v1"
ASSIGNMENT_SCHEMA = "wide-field-solver-source-installation-assignment-v1"
LEGACY_ASSIGNMENT_SCHEMA = "mmto-camera-installation-assignment-v1"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _relative_file(registry_path: Path, target: Path) -> str:
    parent = registry_path.parent.resolve()
    resolved = target.expanduser().resolve(strict=True)
    try:
        relative = resolved.relative_to(parent)
    except ValueError as exc:
        raise ValueError(
            f"calibration artifact must be inside registry root {parent}: {resolved}"
        ) from exc
    return relative.as_posix()


def _resolved_file(registry_path: Path, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise ValueError(f"registry {label} must be a relative path")
    root = registry_path.parent.resolve()
    path = (root / raw).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"registry {label} escapes its registry root: {raw}") from exc
    return path


def _validate_manifest_approval(
    manifest: dict[str, object], registry_root: Path
) -> dict[str, object] | None:
    """Revalidate v25 approval evidence while accepting historical manifests."""
    approval = manifest.get("approval")
    if not isinstance(approval, dict):
        return None
    mode = approval.get("approval_mode")
    if mode is None:
        return None
    if mode == "human_review":
        if "automatic_acceptance" in approval:
            raise ValueError("human approval manifest contains automatic acceptance evidence")
        return None
    if mode != "automated_validation":
        raise ValueError(f"unsupported approval mode: {mode!r}")
    if approval.get("approved_by") != "wide-field-solver-v25-auto":
        raise ValueError("automated approval actor is invalid")
    evidence = approval.get("automatic_acceptance")
    if not isinstance(evidence, dict):
        raise ValueError("automated approval is missing automatic acceptance evidence")
    raw_path = evidence.get("path")
    expected = evidence.get("sha256")
    if (
        not isinstance(raw_path, str)
        or not raw_path
        or Path(raw_path).is_absolute()
        or not isinstance(expected, str)
        or SHA256_PATTERN.fullmatch(expected) is None
    ):
        raise ValueError("automatic acceptance path or SHA-256 is invalid")
    root = registry_root.resolve()
    receipt = (root / raw_path).resolve(strict=True)
    try:
        receipt.relative_to(root)
    except ValueError as exc:
        raise ValueError("automatic acceptance path escapes the registry root") from exc
    if receipt.name != f"{expected}.json":
        raise ValueError("automatic acceptance filename does not match its SHA-256")
    if _sha256(receipt) != expected:
        raise ValueError("automatic acceptance checksum mismatch")
    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("automatic acceptance is unreadable") from exc
    return validate_automatic_acceptance(
        payload,
        expected_identity={
            "source_id": manifest.get("source_id"),
            "camera_id": manifest.get("camera_id"),
            "installation_id": manifest.get("installation_id"),
            "orientation": manifest.get("orientation"),
        },
        expected_finalized_mask_sha256=str(manifest.get("mask_sha256")),
    )


def _registration_core(record: dict[str, object]) -> dict[str, object]:
    fields = (
        "source_id",
        "camera_id",
        "installation_id",
        "mask_id",
        "instrument",
        "detector_shape",
        "plane_layout",
        "plane_names",
        "orientation",
        "coordinate_convention",
        "manifest_sha256",
        "mask_sha256",
    )
    return {name: record.get(name) for name in fields}


def _normalize_record(
    registry_path: Path,
    record: object,
    *,
    line_number: int,
) -> dict[str, object]:
    if not isinstance(record, dict):
        raise ValueError(f"{registry_path}:{line_number}: registry line is not an object")
    if record.get("schema") != REGISTRY_SCHEMA:
        raise ValueError(f"{registry_path}:{line_number}: unsupported registry schema")
    record_type = record.get("record_type")
    if record_type == "activation":
        required = ("source_id", "camera_id", "installation_id", "recorded_utc")
        missing = [name for name in required if record.get(name) in (None, "")]
        if missing:
            raise ValueError(
                f"{registry_path}:{line_number}: activation is missing {missing}"
            )
        answer = dict(record)
        answer["registry_path"] = str(registry_path.resolve())
        answer["registry_line"] = line_number
        return answer
    if record_type != "calibration":
        raise ValueError(
            f"{registry_path}:{line_number}: unsupported record_type {record_type!r}"
        )
    required = (
        "source_id",
        "camera_id",
        "installation_id",
        "mask_id",
        "instrument",
        "detector_shape",
        "plane_layout",
        "plane_names",
        "orientation",
        "coordinate_convention",
        "manifest_path",
        "manifest_sha256",
        "mask_path",
        "mask_sha256",
        "approval",
        "recorded_utc",
    )
    missing = [name for name in required if record.get(name) in (None, "")]
    if missing:
        raise ValueError(
            f"{registry_path}:{line_number}: calibration is missing {missing}"
        )
    manifest_path = _resolved_file(registry_path, record["manifest_path"], "manifest_path")
    mask_path = _resolved_file(registry_path, record["mask_path"], "mask_path")
    manifest_hash = _sha256(manifest_path)
    if manifest_hash != record.get("manifest_sha256"):
        raise ValueError(
            f"{registry_path}:{line_number}: manifest checksum mismatch for {manifest_path}"
        )
    mask_hash = _sha256(mask_path)
    if mask_hash != record.get("mask_sha256"):
        raise ValueError(
            f"{registry_path}:{line_number}: mask checksum mismatch for {mask_path}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"{registry_path}:{line_number}: registered manifest is unreadable"
        ) from exc
    _validate_manifest_approval(manifest, registry_path.parent)
    comparisons = (
        ("installation_id", "installation_id"),
        ("mask_id", "mask_id"),
        ("instrument", "instrument"),
        ("detector_shape", "detector_shape"),
        ("plane_layout", "plane_layout"),
        ("plane_names", "plane_names"),
        ("orientation", "orientation"),
        ("coordinate_convention", "coordinate_convention"),
        ("mask_sha256", "mask_sha256"),
    )
    for registry_name, manifest_name in comparisons:
        if record.get(registry_name) != manifest.get(manifest_name):
            raise ValueError(
                f"{registry_path}:{line_number}: registry {registry_name} conflicts "
                f"with {manifest_path}"
            )
    for identity in ("source_id", "camera_id"):
        if manifest.get(identity) not in (None, record.get(identity)):
            raise ValueError(
                f"{registry_path}:{line_number}: registry {identity} conflicts "
                f"with {manifest_path}"
            )
    expected_mask = (manifest_path.parent / str(manifest.get("mask_file"))).resolve()
    if expected_mask != mask_path:
        raise ValueError(
            f"{registry_path}:{line_number}: mask_path conflicts with manifest mask_file"
        )
    VisibleSkyMask.load(
        manifest_path,
        installation_id=str(record["installation_id"]),
        instrument=str(record["instrument"]),
        detector_shape=tuple(int(value) for value in record["detector_shape"]),
        plane_layout=str(record["plane_layout"]),
        orientation=str(record["orientation"]),
    )
    answer = dict(record)
    answer["manifest_path"] = str(manifest_path)
    answer["mask_path"] = str(mask_path)
    answer["registry_path"] = str(registry_path.resolve())
    answer["registry_line"] = line_number
    return answer


def _parse_stream(stream: IO[str], registry_path: Path) -> list[dict[str, object]]:
    stream.seek(0)
    records: list[dict[str, object]] = []
    for line_number, raw_line in enumerate(stream, 1):
        if not raw_line.strip():
            continue
        try:
            raw = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{registry_path}:{line_number}: malformed or truncated JSONL record"
            ) from exc
        records.append(
            _normalize_record(registry_path, raw, line_number=line_number)
        )
    return records


def _validate_conflicts(
    records: Sequence[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    installations: dict[str, dict[str, object]] = {}
    masks: dict[str, dict[str, object]] = {}
    manifests: dict[str, dict[str, object]] = {}
    answer: list[dict[str, object]] = []
    seen_calibrations: set[str] = set()
    for record in records:
        if record["record_type"] != "calibration":
            answer.append(record)
            continue
        core = _registration_core(record)
        fingerprint = json.dumps(core, sort_keys=True, separators=(",", ":"))
        checks = (
            (masks, str(record["mask_id"]), "mask_id"),
            (manifests, str(record["manifest_sha256"]), "manifest_sha256"),
        )
        for index, key, label in checks:
            prior = index.get(key)
            if prior is not None and _registration_core(prior) != core:
                raise ValueError(
                    f"conflicting calibration registry {label} {key!r}: "
                    f"{prior['registry_path']}:{prior['registry_line']} and "
                    f"{record['registry_path']}:{record['registry_line']}"
                )
            index[key] = record
        if fingerprint not in seen_calibrations:
            answer.append(record)
            seen_calibrations.add(fingerprint)
    registrations = {
        (
            str(record["source_id"]),
            str(record["camera_id"]),
            str(record["installation_id"]),
            str(record["mask_id"]),
        )
        for record in answer
        if record["record_type"] == "calibration"
    }
    for record in answer:
        if record["record_type"] != "activation":
            continue
        target = (
            str(record["source_id"]),
            str(record["camera_id"]),
            str(record["installation_id"]),
            str(record.get("mask_id", "")),
        )
        matched = (
            target in registrations
            if record.get("mask_id")
            else any(candidate[:3] == target[:3] for candidate in registrations)
        )
        if not matched:
            raise ValueError(
                f"activation target is not registered: {target} at "
                f"{record['registry_path']}:{record['registry_line']}"
            )
    return tuple(answer)


def load_registry(paths: Sequence[Path]) -> tuple[dict[str, object], ...]:
    """Read, verify, and combine ordered read-only registry layers."""
    records: list[dict[str, object]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve(strict=True)
        with path.open("r", encoding="utf-8") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
            try:
                records.extend(_parse_stream(stream, path))
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    return _validate_conflicts(records)


def _append_record(
    registry_path: Path,
    raw_record: dict[str, object],
    *,
    idempotent_calibration: bool,
) -> dict[str, object]:
    path = Path(registry_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            existing = _parse_stream(stream, path)
            candidate = _normalize_record(
                path, raw_record, line_number=len(existing) + 1
            )
            _validate_conflicts((*existing, candidate))
            if idempotent_calibration:
                core = _registration_core(candidate)
                prior = next(
                    (
                        record
                        for record in existing
                        if record["record_type"] == "calibration"
                        and _registration_core(record) == core
                    ),
                    None,
                )
                if prior is not None:
                    return prior
            line = json.dumps(raw_record, sort_keys=True, separators=(",", ":"))
            stream.seek(0, os.SEEK_END)
            stream.write(line + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            return candidate
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def register_calibration(
    registry_path: Path,
    manifest_path: Path,
    *,
    source_id: str,
    camera_id: str,
) -> dict[str, object]:
    """Append one approved calibration, or return its identical prior record."""
    registry = Path(registry_path).expanduser().resolve()
    manifest_file = Path(manifest_path).expanduser().resolve(strict=True)
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"approved calibration manifest is unreadable: {manifest_file}"
        ) from exc
    if manifest.get("schema") != "wide-field-solver-visible-sky-mask-v1":
        raise ValueError("approved calibration manifest schema is unsupported")
    if manifest.get("status") != "approved":
        raise ValueError("calibration target is not approved")
    _validate_manifest_approval(manifest, registry.parent)
    for label, supplied in (("source_id", source_id), ("camera_id", camera_id)):
        if not supplied:
            raise ValueError(f"{label} must be non-empty")
        if manifest.get(label) not in (None, supplied):
            raise ValueError(
                f"{label} conflicts with approved manifest: "
                f"{supplied!r} != {manifest.get(label)!r}"
            )
    mask_name = manifest.get("mask_file")
    if not isinstance(mask_name, str) or Path(mask_name).name != mask_name:
        raise ValueError("approved manifest mask_file must be adjacent")
    mask_path = (manifest_file.parent / mask_name).resolve(strict=True)
    VisibleSkyMask.load(
        manifest_file,
        installation_id=str(manifest["installation_id"]),
        instrument=str(manifest["instrument"]),
        detector_shape=tuple(int(value) for value in manifest["detector_shape"]),
        plane_layout=str(manifest["plane_layout"]),
        orientation=str(manifest["orientation"]),
    )
    record = {
        "schema": REGISTRY_SCHEMA,
        "record_type": "calibration",
        "source_id": source_id,
        "camera_id": camera_id,
        "installation_id": manifest["installation_id"],
        "mask_id": manifest["mask_id"],
        "instrument": manifest["instrument"],
        "detector_shape": manifest["detector_shape"],
        "plane_layout": manifest["plane_layout"],
        "plane_names": manifest["plane_names"],
        "orientation": manifest["orientation"],
        "coordinate_convention": manifest["coordinate_convention"],
        "manifest_path": _relative_file(registry, manifest_file),
        "manifest_sha256": _sha256(manifest_file),
        "mask_path": _relative_file(registry, mask_path),
        "mask_sha256": _sha256(mask_path),
        "approval": manifest.get("approval", {}),
        "recorded_utc": _utc_now(),
    }
    return _append_record(registry, record, idempotent_calibration=True)


def activate_installation(
    registry_path: Path,
    *,
    source_id: str,
    camera_id: str,
    installation_id: str,
    mask_id: str | None = None,
) -> dict[str, object]:
    """Append an explicit active-installation selection."""
    path = Path(registry_path).expanduser().resolve(strict=True)
    with path.open("r", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
        try:
            existing = _validate_conflicts(_parse_stream(stream, path))
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    target = next(
        (
            record
            for record in reversed(existing)
            if record["record_type"] == "calibration"
            and record["source_id"] == source_id
            and record["camera_id"] == camera_id
            and record["installation_id"] == installation_id
            and (mask_id is None or record["mask_id"] == mask_id)
        ),
        None,
    )
    if target is None:
        raise ValueError(
            f"installation is not registered for source/camera: "
            f"{source_id}/{camera_id}/{installation_id}"
        )
    record = {
        "schema": REGISTRY_SCHEMA,
        "record_type": "activation",
        "source_id": source_id,
        "camera_id": camera_id,
        "installation_id": installation_id,
        "mask_id": target["mask_id"],
        "recorded_utc": _utc_now(),
    }
    return _append_record(path, record, idempotent_calibration=False)


def active_installation(
    registry_paths: Sequence[Path],
    *,
    source_id: str,
    camera_id: str,
) -> dict[str, object] | None:
    """Resolve the latest explicit activation across ordered registry layers."""
    records = load_registry(registry_paths)
    activation = next(
        (
            record
            for record in reversed(records)
            if record["record_type"] == "activation"
            and record["source_id"] == source_id
            and record["camera_id"] == camera_id
        ),
        None,
    )
    if activation is None:
        return None
    return next(
        record
        for record in reversed(records)
        if record["record_type"] == "calibration"
        and record["source_id"] == source_id
        and record["camera_id"] == camera_id
        and record["installation_id"] == activation["installation_id"]
        and (
            activation.get("mask_id") is None
            or record["mask_id"] == activation["mask_id"]
        )
    )


def _assignment_core(record: dict[str, object]) -> dict[str, object]:
    fields = (
        "source_sha256",
        "source_id",
        "camera_id",
        "installation_id",
        "mask_id",
        "mask_sha256",
        "manifest_sha256",
        "instrument",
        "detector_shape",
        "plane_layout",
        "plane_names",
        "orientation",
    )
    return {name: record.get(name) for name in fields if name in record}


def _parse_assignments(stream: IO[str], path: Path) -> list[dict[str, object]]:
    stream.seek(0)
    answer: list[dict[str, object]] = []
    for line_number, raw in enumerate(stream, 1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid source assignment at {path}:{line_number}") from exc
        if not isinstance(record, dict) or record.get("schema") not in (
            ASSIGNMENT_SCHEMA,
            LEGACY_ASSIGNMENT_SCHEMA,
        ):
            raise ValueError(f"unsupported source assignment at {path}:{line_number}")
        schema = record["schema"]
        generic_required = (
            "source_sha256", "source_id", "camera_id", "installation_id",
            "mask_id", "mask_sha256", "manifest_path", "manifest_sha256",
            "instrument", "detector_shape", "plane_layout", "plane_names",
            "orientation",
        )
        legacy_required = (
            "source_sha256", "installation_id", "mask_id", "mask_sha256",
            "manifest_path", "manifest_sha256", "instrument",
            "detector_shape", "plane_layout", "orientation",
        )
        required = generic_required if schema == ASSIGNMENT_SCHEMA else legacy_required
        missing = [name for name in required if record.get(name) in (None, "")]
        if missing:
            raise ValueError(
                f"invalid source assignment at {path}:{line_number}: "
                f"missing required fields {missing}"
            )
        digest = record.get("source_sha256")
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            raise ValueError(f"invalid source checksum at {path}:{line_number}")
        for name in ("mask_sha256", "manifest_sha256"):
            value = record.get(name)
            if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
                raise ValueError(
                    f"invalid {name} at {path}:{line_number}"
                )
        for name in ("installation_id", "mask_id", "instrument", "plane_layout", "orientation"):
            if not isinstance(record.get(name), str):
                raise ValueError(f"invalid {name} at {path}:{line_number}")
        shape = record.get("detector_shape")
        if (
            not isinstance(shape, list) or len(shape) != 2
            or any(not isinstance(value, int) or value <= 0 for value in shape)
        ):
            raise ValueError(f"invalid detector_shape at {path}:{line_number}")
        if schema == ASSIGNMENT_SCHEMA:
            for name in ("source_id", "camera_id"):
                if not isinstance(record.get(name), str):
                    raise ValueError(f"invalid {name} at {path}:{line_number}")
            planes = record.get("plane_names")
            if not isinstance(planes, list) or not planes or not all(
                isinstance(value, str) and value for value in planes
            ):
                raise ValueError(f"invalid plane_names at {path}:{line_number}")
        answer.append(record)
    return answer


def assignment_for_source(
    assignments_path: Path,
    source_sha256: str,
) -> dict[str, object] | None:
    """Return one immutable assignment, including legacy MMTO records."""
    if SHA256_PATTERN.fullmatch(source_sha256) is None:
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    path = Path(assignments_path).expanduser().resolve()
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"source assignment registry is not a regular file: {path}")
    with path.open("r", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_SH)
        try:
            matches = [
                record
                for record in _parse_assignments(stream, path)
                if record.get("source_sha256") == source_sha256
            ]
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    if not matches:
        return None
    first = _assignment_core(matches[0])
    if any(_assignment_core(record) != first for record in matches[1:]):
        raise ValueError("conflicting source-to-installation assignments")
    return matches[0]


def _append_assignment(
    assignments_path: Path,
    record: dict[str, object],
) -> dict[str, object]:
    path = Path(assignments_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            existing = _parse_assignments(stream, path)
            matches = [
                row
                for row in existing
                if row.get("source_sha256") == record["source_sha256"]
            ]
            if matches:
                existing_core = _assignment_core(matches[0])
                new_core = _assignment_core(record)
                for key, value in existing_core.items():
                    if key in new_core and new_core[key] != value:
                        raise ValueError("conflicting source-to-installation reassignment")
                for row in matches[1:]:
                    if _assignment_core(row) != existing_core:
                        raise ValueError("conflicting source-to-installation assignments")
                return matches[0]
            stream.seek(0, os.SEEK_END)
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            return record
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _source_identity(source: Path, source_sha256: str) -> tuple[Path, dict[str, object]]:
    path = Path(source).expanduser().resolve(strict=True)
    if SHA256_PATTERN.fullmatch(source_sha256) is None:
        raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
    observed = _sha256(path)
    if observed != source_sha256:
        raise ValueError(
            f"source assignment checksum mismatch: expected {source_sha256}, found {observed}"
        )
    image = load_scientific_image(path)
    return path, image.provenance()


def _assignment_for_calibration(
    source: Path,
    source_sha256: str,
    *,
    source_id: str,
    camera_id: str,
    calibration: dict[str, object],
    orientation: str,
) -> dict[str, object]:
    _path, metadata = _source_identity(source, source_sha256)
    checks = (
        ("source", calibration.get("source_id"), source_id),
        ("camera", calibration.get("camera_id"), camera_id),
        ("shape", tuple(calibration["detector_shape"]), tuple(metadata["spatial_shape"])),
        ("layout", calibration["plane_layout"], metadata["channel_layout"]),
        ("orientation", calibration["orientation"], orientation),
    )
    for label, recorded, observed in checks:
        if recorded != observed:
            raise ValueError(
                f"source assignment {label} mismatch: calibration={recorded!r}, "
                f"source={observed!r}"
            )
    if "plane_names" in calibration and tuple(calibration["plane_names"]) != tuple(
        metadata["plane_names"]
    ):
        raise ValueError(
            "source assignment layout plane names mismatch: "
            f"calibration={calibration['plane_names']!r}, source={metadata['plane_names']!r}"
        )
    instrument = metadata.get("instrument")
    if instrument in (None, ""):
        raise ValueError("source assignment instrument identity is unavailable")
    mask = VisibleSkyMask.load(
        Path(str(calibration["manifest_path"])),
        installation_id=str(calibration["installation_id"]),
        instrument=str(instrument),
        detector_shape=tuple(int(value) for value in metadata["spatial_shape"]),
        plane_layout=str(metadata["channel_layout"]),
        orientation=orientation,
    )
    return {
        "schema": ASSIGNMENT_SCHEMA,
        "source_sha256": source_sha256,
        "source_id": source_id,
        "camera_id": camera_id,
        "installation_id": str(calibration["installation_id"]),
        "mask_id": str(mask.mask_id),
        "mask_sha256": str(mask.mask_sha256),
        "manifest_path": str(mask.manifest_path),
        "manifest_sha256": str(calibration["manifest_sha256"]),
        "instrument": str(instrument),
        "detector_shape": list(metadata["spatial_shape"]),
        "plane_layout": str(metadata["channel_layout"]),
        "plane_names": list(metadata["plane_names"]),
        "orientation": orientation,
        "registry_path": str(calibration.get("registry_path", "")),
        "assignment_basis": (
            "operator-selected active installation; validated source checksum, "
            "instrument identity, detector geometry, and approved mask"
        ),
        "recorded_utc": _utc_now(),
    }


def assign_source(
    assignments_path: Path,
    source: Path,
    source_sha256: str,
    *,
    source_id: str,
    camera_id: str,
    registry_paths: Sequence[Path],
    installation_id: str,
    orientation: str,
) -> dict[str, object]:
    """Validate and immutably bind one source checksum to one calibration."""
    registrations = [
        record
        for record in load_registry(registry_paths)
        if record["record_type"] == "calibration"
        and record["source_id"] == source_id
        and record["camera_id"] == camera_id
        and record["installation_id"] == installation_id
    ]
    if len(registrations) != 1:
        raise ValueError(
            f"source assignment requires one registered calibration for "
            f"{source_id}/{camera_id}/{installation_id}, found {len(registrations)}"
        )
    record = _assignment_for_calibration(
        source,
        source_sha256,
        source_id=source_id,
        camera_id=camera_id,
        calibration=registrations[0],
        orientation=orientation,
    )
    return _append_assignment(assignments_path, record)


def validate_source_against_manifest(
    source: Path,
    source_sha256: str,
    manifest_path: Path,
    installation_id: str,
    *,
    source_id: str,
    camera_id: str,
    orientation: str,
) -> dict[str, object]:
    """Validate one source against an exact approved calibration manifest."""
    manifest_file = Path(manifest_path).expanduser().resolve(strict=True)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("status") != "approved":
        raise ValueError("source assignment calibration is not approved")
    if manifest.get("installation_id") != installation_id:
        raise ValueError("source assignment installation mismatch")
    mask_path = manifest_file.parent / str(manifest["mask_file"])
    calibration = {
        "source_id": source_id,
        "camera_id": camera_id,
        "installation_id": installation_id,
        "mask_id": manifest["mask_id"],
        "instrument": manifest["instrument"],
        "detector_shape": manifest["detector_shape"],
        "plane_layout": manifest["plane_layout"],
        "orientation": manifest["orientation"],
        "manifest_path": str(manifest_file),
        "manifest_sha256": _sha256(manifest_file),
        "mask_sha256": _sha256(mask_path),
        "registry_path": "",
    }
    if "plane_names" in manifest:
        calibration["plane_names"] = manifest["plane_names"]
    return _assignment_for_calibration(
        source,
        source_sha256,
        source_id=source_id,
        camera_id=camera_id,
        calibration=calibration,
        orientation=orientation,
    )


def assign_source_to_manifest(
    assignments_path: Path,
    source: Path,
    source_sha256: str,
    manifest_path: Path,
    installation_id: str,
    *,
    source_id: str,
    camera_id: str,
    orientation: str,
) -> dict[str, object]:
    """Compatibility bridge for callers that already selected an exact manifest."""
    record = validate_source_against_manifest(
        source,
        source_sha256,
        manifest_path,
        installation_id,
        source_id=source_id,
        camera_id=camera_id,
        orientation=orientation,
    )
    return _append_assignment(assignments_path, record)


def resolve_source_calibration(
    registry_paths: Sequence[Path],
    assignments_path: Path,
    source_sha256: str,
) -> dict[str, object]:
    """Resolve the calibration frozen into a source checksum assignment."""
    assignment = assignment_for_source(assignments_path, source_sha256)
    if assignment is None:
        raise ValueError(f"source checksum has no installation assignment: {source_sha256}")
    candidates = []
    for record in load_registry(registry_paths):
        if record["record_type"] != "calibration":
            continue
        comparisons = (
            ("installation_id", record["installation_id"]),
            ("mask_id", record["mask_id"]),
            ("mask_sha256", record["mask_sha256"]),
            ("manifest_sha256", record["manifest_sha256"]),
            ("source_id", record["source_id"]),
            ("camera_id", record["camera_id"]),
        )
        if assignment["schema"] == LEGACY_ASSIGNMENT_SCHEMA:
            identity_matches = (
                record["source_id"] == "mmto"
                and record["camera_id"] == "mmto-skycam"
            )
            required_comparisons = comparisons[:4]
        else:
            identity_matches = True
            required_comparisons = comparisons
        if identity_matches and all(
            assignment[key] == expected for key, expected in required_comparisons
        ):
            candidates.append(record)
    if len(candidates) != 1:
        raise ValueError(
            f"source assignment resolves to {len(candidates)} calibrations: {source_sha256}"
        )
    answer = dict(candidates[0])
    answer["assignment"] = assignment
    return answer
