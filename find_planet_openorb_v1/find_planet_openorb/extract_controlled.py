from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
from typing import Mapping, Sequence

from .provenance import open_sqlite_read_only, sha256_file
from .types import CameraReceipt, SelectedCentroid


PINNED_CONTROLLED_AUDIT_SHA256 = "e0f445e044382369aa4a468a53900b1192cd7859389b9c388dd00c8633be6924"
REQUIRED_AUDIT_FIELDS = {
    "night", "channel", "planet", "observation_time_utc", "source_path",
    "source_sha256", "run_id", "detection_id", "source_class", "identity_status",
    "metadata_association_status", "association_measured_x_px",
    "association_measured_y_px", "stellar_only_fit_rms_arcmin",
}


class ControlledExtractionError(ValueError):
    pass


def _finite_float(value: str, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ControlledExtractionError(f"{field} must be numeric") from error
    if not math.isfinite(parsed):
        raise ControlledExtractionError(f"{field} must be finite")
    return parsed


def _boolean(value: str, field: str) -> bool:
    normalised = value.strip().lower()
    if normalised == "true":
        return True
    if normalised == "false":
        return False
    raise ControlledExtractionError(f"{field} must be True or False")


def select_answer_key_rows(
    audit_path: Path,
    expected_sha256: str = PINNED_CONTROLLED_AUDIT_SHA256,
    object_name: str = "Mars",
) -> tuple[list[SelectedCentroid], list[dict[str, str]]]:
    audit_path = Path(audit_path)
    actual_sha256 = sha256_file(audit_path)
    if actual_sha256 != expected_sha256:
        raise ControlledExtractionError(
            f"audit SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    with audit_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        missing = sorted(REQUIRED_AUDIT_FIELDS - fields)
        if missing:
            raise ControlledExtractionError(f"audit is missing required fields: {', '.join(missing)}")
        if "saturated" not in fields and not {"saturation_known", "channel_saturated"} <= fields:
            raise ControlledExtractionError(
                "audit needs saturated or the saturation_known/channel_saturated pair"
            )
        original_rows = [dict(row) for row in reader]

    selected: list[SelectedCentroid] = []
    audited: list[dict[str, str]] = []
    selected_hashes: set[str] = set()
    for original in original_rows:
        row = dict(original)
        reason = ""
        if row["channel"] != "B":
            reason = "different_channel"
        elif row["planet"] != object_name:
            reason = "different_answer_key_object"
        elif row["identity_status"] != "metadata_time_match":
            reason = "identity_not_metadata_time_match"
        elif row["metadata_association_status"] != "metadata_time_associated":
            reason = "metadata_association_unavailable"
        elif not row["source_sha256"]:
            reason = "missing_source_sha256"
        elif row["source_sha256"] in selected_hashes:
            reason = "duplicate_source_sha256"
        if not reason:
            x_px = _finite_float(row["association_measured_x_px"], "measured x")
            y_px = _finite_float(row["association_measured_y_px"], "measured y")
            fit_rms = _finite_float(row["stellar_only_fit_rms_arcmin"], "stellar-only fit RMS")
            if fit_rms <= 0:
                raise ControlledExtractionError("stellar-only fit RMS must be positive")
            if "saturated" in row:
                saturated = _boolean(row["saturated"], "saturated")
            else:
                if not _boolean(row["saturation_known"], "saturation known"):
                    raise ControlledExtractionError("selected row has no known channel saturation state")
                saturated = _boolean(row["channel_saturated"], "channel saturated")
            selected.append(SelectedCentroid(
                run_id=row["run_id"], source_sha256=row["source_sha256"],
                source_path=row["source_path"], night=row["night"],
                observation_time_utc=row["observation_time_utc"], detection_id=row["detection_id"],
                x_px=x_px, y_px=y_px, stellar_fit_rms_arcmin=fit_rms,
                source_class=row["source_class"], saturated=saturated,
            ))
            selected_hashes.add(row["source_sha256"])
            row.update(answer_key_selection_status="selected", answer_key_selection_reason="", anonymous_object_id="Object A")
        else:
            row.update(answer_key_selection_status="rejected", answer_key_selection_reason=reason, anonymous_object_id="")
        audited.append(row)
    selected.sort(key=lambda item: (item.observation_time_utc, item.run_id))
    return selected, audited


def load_exact_receipts(database: Path, rows: Sequence[SelectedCentroid]) -> dict[str, CameraReceipt]:
    receipts: dict[str, CameraReceipt] = {}
    connection = open_sqlite_read_only(database)
    try:
        for selected in rows:
            matches = connection.execute(
                "SELECT run_id, source_path, source_sha256, exit_code, solver_version, result_json FROM runs WHERE run_id=?",
                (selected.run_id,),
            ).fetchall()
            if len(matches) != 1:
                raise ControlledExtractionError(
                    f"run {selected.run_id} must have exactly one exact receipt; found {len(matches)}"
                )
            run_id, source_path, source_sha256, exit_code, solver_version, result_json = matches[0]
            if int(exit_code) != 0:
                raise ControlledExtractionError(f"run {run_id} is a failed receipt")
            if source_sha256 != selected.source_sha256:
                raise ControlledExtractionError(f"run {run_id} source SHA does not match the selected row")
            try:
                result = json.loads(result_json)
            except (TypeError, json.JSONDecodeError) as error:
                raise ControlledExtractionError(f"run {run_id} has malformed result JSON") from error
            camera = result.get("camera") if isinstance(result, dict) else None
            if not isinstance(camera, dict) or not camera:
                raise ControlledExtractionError(f"run {run_id} has no parseable saved camera")
            receipts[run_id] = CameraReceipt(
                run_id=run_id, source_sha256=source_sha256, source_path=source_path,
                solver_version=str(solver_version or ""), camera=camera,
            )
    finally:
        connection.close()
    return receipts


def write_answer_key_audit(path: Path, audit_rows: Sequence[Mapping[str, str]]) -> None:
    if not audit_rows:
        raise ControlledExtractionError("answer-key audit needs at least one row")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit_rows[0]))
        writer.writeheader()
        writer.writerows(audit_rows)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
