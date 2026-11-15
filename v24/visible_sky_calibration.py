"""Camera-neutral inputs and detector identity for visible-sky calibration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from typing import Sequence

import numpy as np
from PIL import Image
from scipy.ndimage import binary_erosion

if __package__:
    from .point_star_image import load_scientific_image
    from .point_star_visible_sky import VisibleSkyMask, compatible_instrument_identity
else:
    from point_star_image import load_scientific_image
    from point_star_visible_sky import VisibleSkyMask, compatible_instrument_identity


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class CalibrationSource:
    path: Path
    source_sha256: str
    observed_bytes: int
    source_id: str
    camera_id: str
    observed_utc: str
    observation_date: str
    remote_url: str


@dataclass(frozen=True)
class DetectorSignature:
    spatial_shape: tuple[int, int]
    channel_layout: str
    plane_names: tuple[str, ...]
    instrument: str | None
    orientation: str


@dataclass(frozen=True)
class CalibrationSplit:
    calibration_dates: tuple[str, ...]
    holdout_dates: tuple[str, ...]
    calibration_sources: tuple[CalibrationSource, ...]
    holdout_sources: tuple[CalibrationSource, ...]
    selected_calibration_sources: tuple[CalibrationSource, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _observation_date(observed_utc: str, remote_url: str) -> str:
    try:
        parsed = datetime.fromisoformat(observed_utc.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"invalid observed_utc for download record {remote_url}: {observed_utc!r}"
        ) from exc
    return parsed.date().isoformat()


def verified_sources_from_manifest(
    manifest_path: Path,
    archive_root: Path,
    source_id: str,
    camera_id: str,
) -> tuple[CalibrationSource, ...]:
    """Return freshly verified managed originals for one source and camera."""
    manifest = Path(manifest_path).expanduser().resolve(strict=True)
    root = Path(archive_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    if not source_id or not camera_id:
        raise ValueError("source_id and camera_id must be non-empty")
    uri = f"{manifest.as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT remote_url, source_id, camera_id, observed_utc, local_path,
                   observed_bytes, sha256
            FROM downloads
            WHERE source_id=? AND camera_id=?
              AND download_status='downloaded'
              AND validation_status='verified'
            ORDER BY observed_utc, remote_url
            """,
            (source_id, camera_id),
        ).fetchall()
    answer: list[CalibrationSource] = []
    for row in rows:
        url = str(row["remote_url"])
        local_path = row["local_path"]
        if not isinstance(local_path, str) or not local_path:
            raise ValueError(f"verified download record has no local_path: {url}")
        path = (root / local_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"download path is outside archive root for {url}: {local_path}"
            ) from exc
        if not path.is_file():
            raise FileNotFoundError(f"verified download is missing for {url}: {path}")
        expected_size = row["observed_bytes"]
        if not isinstance(expected_size, int) or path.stat().st_size != expected_size:
            raise ValueError(
                f"size mismatch for {url}: expected {expected_size}, "
                f"found {path.stat().st_size} at {path}"
            )
        expected_hash = row["sha256"]
        observed_hash = _sha256(path)
        if not isinstance(expected_hash, str) or observed_hash != expected_hash:
            raise ValueError(
                f"checksum mismatch for {url}: expected {expected_hash}, "
                f"found {observed_hash} at {path}"
            )
        observed_utc = str(row["observed_utc"])
        answer.append(
            CalibrationSource(
                path=path,
                source_sha256=observed_hash,
                observed_bytes=expected_size,
                source_id=str(row["source_id"]),
                camera_id=str(row["camera_id"]),
                observed_utc=observed_utc,
                observation_date=_observation_date(observed_utc, url),
                remote_url=url,
            )
        )
    return tuple(answer)


def detector_signature(path: Path, *, orientation: str) -> DetectorSignature:
    """Decode one original and return its installation-sensitive identity."""
    if not isinstance(orientation, str) or not orientation.strip():
        raise ValueError("orientation must be a non-empty string")
    image = load_scientific_image(Path(path))
    metadata = image.provenance()
    instrument = metadata.get("instrument")
    if instrument is not None:
        instrument = str(instrument).strip() or None
    return DetectorSignature(
        spatial_shape=tuple(int(value) for value in image.shape),
        channel_layout=str(metadata["channel_layout"]),
        plane_names=tuple(str(value) for value in metadata["plane_names"]),
        instrument=instrument,
        orientation=orientation.strip(),
    )


def require_single_detector_signature(
    records: Sequence[tuple[Path, DetectorSignature]],
) -> DetectorSignature:
    """Reject a calibration population containing more than one detector identity."""
    if not records:
        raise ValueError("at least one detector signature is required")
    first_path, expected = records[0]
    fields = (
        "spatial_shape",
        "channel_layout",
        "plane_names",
        "instrument",
        "orientation",
    )
    for path, observed in records[1:]:
        for field in fields:
            expected_value = getattr(expected, field)
            observed_value = getattr(observed, field)
            compatible = (
                compatible_instrument_identity(expected_value, observed_value)
                if field == "instrument"
                and expected_value is not None
                and observed_value is not None
                else expected_value == observed_value
            )
            if not compatible:
                raise ValueError(
                    f"mixed detector signatures: {field} differs between "
                    f"{first_path} ({expected_value!r}) and "
                    f"{path} ({observed_value!r})"
                )
    return expected


def partition_dates(
    sources: Sequence[CalibrationSource],
    *,
    holdout_modulus: int = 5,
    holdout_remainder: int = 0,
) -> CalibrationSplit:
    """Split whole dates first, then select one phase-cycled calibration frame."""
    if holdout_modulus <= 0:
        raise ValueError("holdout_modulus must be positive")
    if not 0 <= holdout_remainder < holdout_modulus:
        raise ValueError("holdout_remainder must be within the modulus")
    ordered = tuple(
        sorted(
            sources,
            key=lambda item: (
                item.observation_date,
                item.observed_utc,
                item.path.name,
                str(item.path),
            ),
        )
    )
    dates = tuple(sorted({source.observation_date for source in ordered}))
    if len(dates) < 2:
        raise ValueError("at least two observing dates are required for a held-out split")
    holdout_dates = tuple(
        value
        for index, value in enumerate(dates)
        if index % holdout_modulus == holdout_remainder
    )
    if not holdout_dates:
        holdout_dates = (dates[holdout_remainder % len(dates)],)
    minimum_holdout = math.ceil(len(dates) / 5)
    if len(holdout_dates) < minimum_holdout:
        selected = set(holdout_dates)
        holdout_dates = holdout_dates + tuple(
            value for value in dates if value not in selected
        )[: minimum_holdout - len(holdout_dates)]
        holdout_dates = tuple(sorted(holdout_dates))
    holdout = set(holdout_dates)
    calibration_dates = tuple(value for value in dates if value not in holdout)
    calibration_sources = tuple(
        source for source in ordered if source.observation_date not in holdout
    )
    holdout_sources = tuple(
        source for source in ordered if source.observation_date in holdout
    )
    phases = (0.25, 0.50, 0.75)
    selected: list[CalibrationSource] = []
    for ordinal, value in enumerate(calibration_dates):
        members = [
            source for source in calibration_sources if source.observation_date == value
        ]
        index = round(phases[ordinal % len(phases)] * (len(members) - 1))
        selected.append(members[index])
    return CalibrationSplit(
        calibration_dates=calibration_dates,
        holdout_dates=holdout_dates,
        calibration_sources=calibration_sources,
        holdout_sources=holdout_sources,
        selected_calibration_sources=tuple(selected),
    )


def draft_filename(installation_id: str) -> str:
    """Return a safe, installation-derived review-only mask filename."""
    if not isinstance(installation_id, str) or not SAFE_IDENTIFIER.fullmatch(
        installation_id
    ):
        raise ValueError(
            "installation_id must match [A-Za-z0-9][A-Za-z0-9._-]*"
        )
    return f"{installation_id}.draft.png"


def artifact_inventory_sha256(artifacts: dict[str, str]) -> str:
    """Hash one canonical adjacent-artifact inventory."""
    payload = json.dumps(artifacts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def proposal_metadata_sha256(proposal: dict[str, object]) -> str:
    """Hash all immutable proposal metadata, including the artifact inventory."""
    payload = {key: value for key, value in proposal.items() if key != "seal"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def seal_artifact_inventory(
    artifacts: dict[str, str], proposal: dict[str, object] | None = None
) -> dict[str, str]:
    seal = {
        "status": "sealed",
        "artifact_inventory_sha256": artifact_inventory_sha256(artifacts),
    }
    if proposal is not None:
        seal["proposal_metadata_sha256"] = proposal_metadata_sha256(proposal)
    return seal


def _selection_payload(selection_path: Path) -> tuple[Path, dict[str, object]]:
    path = Path(selection_path).expanduser().resolve(strict=True)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"proposal selection is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"proposal selection must be a JSON object: {path}")
    if payload.get("status") != "draft_not_approved" or payload.get(
        "production_eligible"
    ) is not False:
        raise ValueError("proposal is not a review-only draft")
    required = (
        "source_id",
        "camera_id",
        "installation_id",
        "orientation",
        "detector_signature",
        "coordinate_convention",
        "generation_code_sha256",
        "artifacts",
        "seal",
    )
    missing = [name for name in required if payload.get(name) in (None, "")]
    if missing:
        raise ValueError(f"proposal is missing identity or seal fields: {missing}")
    signature = payload["detector_signature"]
    if not isinstance(signature, dict):
        raise ValueError("proposal detector_signature must be an object")
    signature_required = (
        "spatial_shape",
        "channel_layout",
        "plane_names",
        "instrument",
        "orientation",
    )
    signature_missing = [
        name for name in signature_required if signature.get(name) in (None, "")
    ]
    if signature_missing:
        raise ValueError(
            f"proposal detector signature is missing fields: {signature_missing}"
        )
    if signature.get("orientation") != payload.get("orientation"):
        raise ValueError("proposal orientation conflicts with detector signature")
    for name in ("source_id", "camera_id", "installation_id"):
        value = payload.get(name)
        if not isinstance(value, str) or SAFE_IDENTIFIER.fullmatch(value) is None:
            raise ValueError(
                f"proposal {name} must match [A-Za-z0-9][A-Za-z0-9._-]*"
            )
    artifacts = payload["artifacts"]
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("proposal artifact inventory is empty")
    normalized: dict[str, str] = {}
    for raw_name, raw_digest in artifacts.items():
        if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
            raise ValueError(f"proposal artifact path must be adjacent: {raw_name!r}")
        if not isinstance(raw_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", raw_digest
        ):
            raise ValueError(f"proposal artifact checksum is invalid: {raw_name}")
        artifact = path.parent / raw_name
        try:
            observed = _sha256(artifact)
        except OSError as exc:
            raise FileNotFoundError(f"proposal artifact is missing: {artifact}") from exc
        if observed != raw_digest:
            raise ValueError(f"proposal artifact checksum mismatch: {artifact}")
        normalized[raw_name] = raw_digest
    draft_names = [name for name in normalized if name.endswith(".draft.png")]
    if len(draft_names) != 1:
        raise ValueError("proposal must contain exactly one draft PNG")
    if "temporal_reference.png" not in normalized:
        raise ValueError("proposal has no sealed temporal reference")
    seal = payload["seal"]
    if not isinstance(seal, dict) or seal.get("status") != "sealed":
        raise ValueError("proposal draft was never sealed")
    expected_inventory = artifact_inventory_sha256(normalized)
    if seal.get("artifact_inventory_sha256") != expected_inventory:
        raise ValueError("proposal artifact inventory seal mismatch")
    expected_metadata = proposal_metadata_sha256(payload)
    if seal.get("proposal_metadata_sha256") != expected_metadata:
        raise ValueError("proposal metadata seal mismatch")
    payload["artifacts"] = normalized
    return path, payload


def _binary_mask(path: Path, *, expected_shape: tuple[int, int] | None = None) -> np.ndarray:
    source = Path(path).expanduser().resolve(strict=True)
    with Image.open(source) as image:
        pixels = np.asarray(image.convert("L"), dtype=np.uint8)
    if expected_shape is not None and pixels.shape != expected_shape:
        raise ValueError(
            f"edited mask shape {pixels.shape} does not match proposal {expected_shape}"
        )
    values = set(np.unique(pixels).tolist())
    if not values.issubset({0, 255}):
        raise ValueError(f"mask must be binary 0/255, found {sorted(values)}")
    return pixels


def _review_overlay(reference: np.ndarray, visible: np.ndarray, *, inverted: bool) -> np.ndarray:
    base = np.asarray(reference, dtype=np.uint8).copy()
    if inverted:
        base = 255 - base
    excluded = ~visible
    tint = np.array([35, 90, 225] if inverted else [220, 35, 45], dtype=float)
    base[excluded] = np.rint(0.58 * base[excluded] + 0.42 * tint).astype(np.uint8)
    boundary = visible & ~binary_erosion(visible)
    base[boundary] = np.array([255, 235, 0], dtype=np.uint8)
    return base


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def revise_proposal(
    parent_selection: Path,
    edited_mask: Path,
    output: Path,
) -> Path:
    """Write an immutable child proposal from one reviewed binary edit."""
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(destination)
    parent_path, parent = _selection_payload(parent_selection)
    expected_shape = tuple(int(value) for value in parent["spatial_shape"])
    edited_path = Path(edited_mask).expanduser().resolve(strict=True)
    pixels = _binary_mask(edited_path, expected_shape=expected_shape)
    reference_path = parent_path.parent / "temporal_reference.png"
    with Image.open(reference_path) as image:
        reference = np.asarray(image.convert("RGB"), dtype=np.uint8)
    if reference.shape[:2] != expected_shape:
        raise ValueError(
            f"temporal reference shape {reference.shape[:2]} does not match {expected_shape}"
        )
    destination.mkdir(parents=True, exist_ok=False)
    draft_name = draft_filename(str(parent["installation_id"]))
    draft_path = destination / draft_name
    Image.fromarray(pixels, mode="L").save(draft_path)
    temporal_path = destination / "temporal_reference.png"
    temporal_path.write_bytes(reference_path.read_bytes())
    visible = pixels == 255
    review_path = destination / "boundary_review.png"
    inverted_path = destination / "boundary_review_inverted.png"
    Image.fromarray(
        _review_overlay(reference, visible, inverted=False), mode="RGB"
    ).save(review_path)
    Image.fromarray(
        _review_overlay(reference, visible, inverted=True), mode="RGB"
    ).save(inverted_path)
    artifacts = {
        path.name: _sha256(path)
        for path in (draft_path, temporal_path, review_path, inverted_path)
    }
    payload = json.loads(json.dumps(parent))
    payload["draft_id"] = (
        f"{parent['installation_id']}-revision-{_sha256(edited_path)[:12]}"
    )
    payload["artifacts"] = artifacts
    payload["revision"] = {
        "parent_selection": str(parent_path),
        "parent_selection_sha256": _sha256(parent_path),
        "parent_artifact_inventory": parent["artifacts"],
        "parent_artifact_inventory_sha256": parent["seal"][
            "artifact_inventory_sha256"
        ],
        "edited_mask": str(edited_path),
        "edited_mask_sha256": _sha256(edited_path),
    }
    payload.pop("seal", None)
    payload["seal"] = seal_artifact_inventory(artifacts, payload)
    selection_path = destination / "selection.json"
    _write_json(selection_path, payload)
    for artifact in (draft_path, temporal_path, review_path, inverted_path):
        with artifact.open("rb") as stream:
            os.fsync(stream.fileno())
    _fsync_directory(destination)
    return selection_path


def finalize_binary_mask(
    draft_path: Path,
    output_path: Path,
    *,
    safety_margin_pixels: int,
) -> dict[str, object]:
    """Apply the reviewed inward margin and write one immutable binary PNG."""
    draft = Path(draft_path).expanduser().resolve(strict=True)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise FileExistsError(output)
    if safety_margin_pixels < 0:
        raise ValueError("safety margin must be non-negative")
    pixels = _binary_mask(draft)
    visible = pixels == 255
    approved = (
        binary_erosion(visible, iterations=safety_margin_pixels)
        if safety_margin_pixels
        else visible.copy()
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.where(approved, 255, 0).astype(np.uint8), mode="L").save(output)
    return {
        "draft_path": str(draft),
        "draft_sha256": _sha256(draft),
        "approved_path": str(output),
        "approved_sha256": _sha256(output),
        "safety_margin_pixels": int(safety_margin_pixels),
        "draft_visible_pixels": int(visible.sum()),
        "approved_visible_pixels": int(approved.sum()),
        "excluded_pixels_added": int(visible.sum() - approved.sum()),
    }


def approve_proposal(
    proposal_selection: Path,
    calibration_root: Path,
    *,
    reviewed_draft_sha256: str,
    mask_id: str,
    approved_by: str,
    safety_margin_pixels: int,
) -> Path:
    """Freeze and production-validate one exact sealed review proposal."""
    if not SAFE_IDENTIFIER.fullmatch(mask_id):
        raise ValueError("mask_id must match [A-Za-z0-9][A-Za-z0-9._-]*")
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise ValueError("approved_by must be a non-empty string")
    if safety_margin_pixels < 0:
        raise ValueError("safety margin must be non-negative")
    selection_path, selection = _selection_payload(proposal_selection)
    artifacts = selection["artifacts"]
    draft_names = [name for name in artifacts if name.endswith(".draft.png")]
    draft_name = draft_names[0]
    actual_draft_hash = artifacts[draft_name]
    if reviewed_draft_sha256 != actual_draft_hash:
        raise ValueError(
            "reviewed draft checksum does not identify the sealed proposal draft"
        )
    signature = selection["detector_signature"]
    installation_id = str(selection["installation_id"])
    root = Path(calibration_root).expanduser().resolve()
    destination = root / installation_id
    if destination.exists():
        raise FileExistsError(destination)
    if root.exists():
        for candidate in root.rglob("*.json"):
            try:
                existing = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if existing.get("mask_id") == mask_id:
                raise ValueError(f"mask_id already exists: {mask_id} at {candidate}")
            if existing.get("installation_id") == installation_id:
                raise ValueError(
                    f"installation_id already exists: {installation_id} at {candidate}"
                )
    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{installation_id}.", dir=root))
    mask_path = temporary / f"{mask_id}.png"
    manifest_path = temporary / f"{mask_id}.json"
    try:
        finalization = finalize_binary_mask(
            selection_path.parent / draft_name,
            mask_path,
            safety_margin_pixels=safety_margin_pixels,
        )
        now = datetime.now(timezone.utc)
        manifest = {
            "schema": "wide-field-solver-visible-sky-mask-v1",
            "status": "approved",
            "source_id": selection["source_id"],
            "camera_id": selection["camera_id"],
            "mask_id": mask_id,
            "installation_id": installation_id,
            "instrument": signature["instrument"],
            "detector_shape": signature["spatial_shape"],
            "plane_layout": signature["channel_layout"],
            "plane_names": signature["plane_names"],
            "orientation": signature["orientation"],
            "coordinate_convention": selection["coordinate_convention"],
            "mask_file": mask_path.name,
            "mask_sha256": finalization["approved_sha256"],
            "mask_values": {"0": "excluded", "255": "visible_sky"},
            "safety_margin_pixels": int(safety_margin_pixels),
            "draft_visible_pixels": finalization["draft_visible_pixels"],
            "approved_visible_pixels": finalization["approved_visible_pixels"],
            "excluded_pixels_added_by_safety_margin": finalization[
                "excluded_pixels_added"
            ],
            "approved_visible_fraction": (
                finalization["approved_visible_pixels"]
                / int(np.prod(signature["spatial_shape"]))
            ),
            "review": {
                "selection_file": str(selection_path),
                "selection_sha256": _sha256(selection_path),
                "reviewed_draft_file": str(selection_path.parent / draft_name),
                "reviewed_draft_sha256": actual_draft_hash,
                "artifact_inventory_sha256": selection["seal"][
                    "artifact_inventory_sha256"
                ],
            },
            "approval": {
                "approved_by": approved_by.strip(),
                "approved_utc": now.isoformat().replace("+00:00", "Z"),
                "reviewed_draft_sha256": actual_draft_hash,
            },
            "generation": {
                "proposal_code_sha256": selection["generation_code_sha256"],
                "finalization_code_sha256": _sha256(Path(__file__)),
                "method": selection.get("proposal", {}),
            },
            "source_selection": selection.get("selection", {}),
        }
        _write_json(manifest_path, manifest)
        VisibleSkyMask.load(
            manifest_path,
            installation_id=installation_id,
            instrument=str(signature["instrument"]),
            detector_shape=tuple(int(value) for value in signature["spatial_shape"]),
            plane_layout=str(signature["channel_layout"]),
            orientation=str(signature["orientation"]),
        )
        _fsync_directory(temporary)
        os.replace(temporary, destination)
        _fsync_directory(root)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
    return destination / manifest_path.name
