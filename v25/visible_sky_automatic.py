"""Pure gates and content-addressed evidence for automatic mask acceptance."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
from typing import Mapping, Sequence

AUTOMATIC_ACCEPTANCE_SCHEMA = "visible-sky-automatic-v1"
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
AUTOMATIC_ACCEPTANCE_THRESHOLDS = MappingProxyType(
    {
        "total_date_count_minimum": 10,
        "calibration_date_count_minimum": 8,
        "held_out_date_count_minimum": 2,
        "held_out_source_count_minimum": 20,
        "detector_signature_count_exact": 1,
        "proposal_visible_fraction_minimum": 0.10,
        "proposal_visible_fraction_maximum": 0.95,
        "proposal_connected_component_count_exact": 1,
        "finalized_visible_fraction_minimum": 0.10,
        "finalized_visible_fraction_maximum": 0.95,
        "finalized_connected_component_count_exact": 1,
        "held_out_footprint_iou_median_minimum": 0.80,
        "held_out_footprint_iou_minimum_minimum": 0.50,
        "held_out_unmasked_detection_count_minimum": 100,
        "held_out_boundary_intersection_fraction_maximum": 0.05,
        "fold_count_exact": 5,
        "fold_mask_iou_minimum": 0.95,
        "fold_boundary_distance_mean_pixels_maximum": 10.0,
        "fold_boundary_distance_p95_pixels_maximum": 24.0,
    }
)

_METRIC_KEYS = (
    "total_date_count",
    "calibration_date_count",
    "held_out_date_count",
    "held_out_source_count",
    "detector_signature_count",
    "proposal_visible_pixel_count",
    "proposal_pixel_count",
    "proposal_connected_component_count",
    "finalized_visible_pixel_count",
    "finalized_pixel_count",
    "finalized_connected_component_count",
    "held_out_footprint_iou_median_numerator",
    "held_out_footprint_iou_median_denominator",
    "held_out_footprint_iou_minimum_numerator",
    "held_out_footprint_iou_minimum_denominator",
    "held_out_unmasked_detection_count",
    "held_out_boundary_intersection_count",
)
_FOLD_KEYS = (
    "fold_index",
    "mask_intersection_count",
    "mask_union_count",
    "boundary_distance_mean_pixels",
    "boundary_distance_p95_pixels",
)
_IDENTITY_KEYS = (
    "source_id",
    "camera_id",
    "installation_id",
    "orientation",
    "detector_signature_sha256",
)
_SHA256_LENGTH = 64


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _nonnegative_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _check(
    gate: str,
    observed: int | float,
    relation: str,
    limit: int | float,
    passed: bool,
    *,
    numerator: int | None = None,
    denominator: int | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "gate": gate,
        "observed": observed,
        "relation": relation,
        "limit": limit,
        "passed": passed,
    }
    if numerator is not None:
        row["numerator"] = numerator
    if denominator is not None:
        row["denominator"] = denominator
    return row


def _invalid(gate: str, value: object = None) -> dict[str, object]:
    return {
        "gate": gate,
        "observed": repr(value),
        "relation": "valid finite value required",
        "limit": None,
        "passed": False,
    }


def evaluate_automatic_gates(
    metrics: Mapping[str, object],
    fold_metrics: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Evaluate the fixed v25 automatic gates without reading external state."""
    checks: list[dict[str, object]] = []
    invalid_metrics: set[str] = set()

    for key in _METRIC_KEYS:
        if key not in metrics:
            checks.append(_invalid(f"missing_{key}"))
            invalid_metrics.add(key)
            continue
        value = metrics.get(key)
        if not _nonnegative_integer(value):
            checks.append(_invalid(f"invalid_{key}", value))
            invalid_metrics.add(key)

    def scalar_gate(metric: str, suffix: str, relation: str) -> None:
        if metric in invalid_metrics:
            return
        gate = f"{metric}_{suffix}"
        observed = metrics[metric]
        limit = AUTOMATIC_ACCEPTANCE_THRESHOLDS[gate]
        if relation == ">=":
            passed = observed >= limit
        elif relation == "<=":
            passed = observed <= limit
        else:
            passed = observed == limit
        checks.append(_check(gate, observed, relation, limit, passed))

    scalar_gate("total_date_count", "minimum", ">=")
    scalar_gate("calibration_date_count", "minimum", ">=")
    scalar_gate("held_out_date_count", "minimum", ">=")
    scalar_gate("held_out_source_count", "minimum", ">=")
    scalar_gate("detector_signature_count", "exact", "==")

    if not {"proposal_visible_pixel_count", "proposal_pixel_count"} & invalid_metrics:
        denominator = metrics["proposal_pixel_count"]
        numerator = metrics["proposal_visible_pixel_count"]
        if denominator == 0:
            checks.append(_invalid("invalid_proposal_pixel_count", denominator))
        else:
            fraction = numerator / denominator
            for suffix, relation in (("minimum", ">="), ("maximum", "<=")):
                gate = f"proposal_visible_fraction_{suffix}"
                limit = AUTOMATIC_ACCEPTANCE_THRESHOLDS[gate]
                passed = fraction >= limit if relation == ">=" else fraction <= limit
                checks.append(
                    _check(
                        gate,
                        fraction,
                        relation,
                        limit,
                        passed,
                        numerator=numerator,
                        denominator=denominator,
                    )
                )

    scalar_gate("proposal_connected_component_count", "exact", "==")

    if not {"finalized_visible_pixel_count", "finalized_pixel_count"} & invalid_metrics:
        denominator = metrics["finalized_pixel_count"]
        numerator = metrics["finalized_visible_pixel_count"]
        if denominator == 0:
            checks.append(_invalid("invalid_finalized_pixel_count", denominator))
        else:
            fraction = numerator / denominator
            for suffix, relation in (("minimum", ">="), ("maximum", "<=")):
                gate = f"finalized_visible_fraction_{suffix}"
                limit = AUTOMATIC_ACCEPTANCE_THRESHOLDS[gate]
                passed = fraction >= limit if relation == ">=" else fraction <= limit
                checks.append(
                    _check(
                        gate,
                        fraction,
                        relation,
                        limit,
                        passed,
                        numerator=numerator,
                        denominator=denominator,
                    )
                )
    scalar_gate("finalized_connected_component_count", "exact", "==")

    for prefix in ("held_out_footprint_iou_median", "held_out_footprint_iou_minimum"):
        numerator_key = f"{prefix}_numerator"
        denominator_key = f"{prefix}_denominator"
        if {numerator_key, denominator_key} & invalid_metrics:
            continue
        numerator = metrics[numerator_key]
        denominator = metrics[denominator_key]
        if denominator == 0:
            checks.append(_invalid(f"invalid_{denominator_key}", denominator))
            continue
        gate = f"{prefix}_minimum"
        limit = AUTOMATIC_ACCEPTANCE_THRESHOLDS[gate]
        observed = numerator / denominator
        checks.append(
            _check(
                gate,
                observed,
                ">=",
                limit,
                observed >= limit,
                numerator=numerator,
                denominator=denominator,
            )
        )

    scalar_gate("held_out_unmasked_detection_count", "minimum", ">=")
    boundary_keys = {
        "held_out_boundary_intersection_count",
        "held_out_unmasked_detection_count",
    }
    if not boundary_keys & invalid_metrics:
        numerator = metrics["held_out_boundary_intersection_count"]
        denominator = metrics["held_out_unmasked_detection_count"]
        if denominator == 0:
            checks.append(_invalid("invalid_held_out_unmasked_detection_count", denominator))
        else:
            gate = "held_out_boundary_intersection_fraction_maximum"
            limit = AUTOMATIC_ACCEPTANCE_THRESHOLDS[gate]
            observed = numerator / denominator
            checks.append(
                _check(
                    gate,
                    observed,
                    "<=",
                    limit,
                    observed <= limit,
                    numerator=numerator,
                    denominator=denominator,
                )
            )

    fold_count_gate = "fold_count_exact"
    fold_count_limit = AUTOMATIC_ACCEPTANCE_THRESHOLDS[fold_count_gate]
    checks.append(
        _check(
            fold_count_gate,
            len(fold_metrics),
            "==",
            fold_count_limit,
            len(fold_metrics) == fold_count_limit,
        )
    )
    if len(fold_metrics) == fold_count_limit:
        seen_indices: set[int] = set()
        for ordinal, fold in enumerate(fold_metrics):
            index = fold.get("fold_index")
            if not _nonnegative_integer(index) or index in seen_indices:
                checks.append(_invalid(f"invalid_fold_{ordinal}_fold_index", index))
                continue
            seen_indices.add(index)
            invalid_fold_keys: set[str] = set()
            for key in _FOLD_KEYS[1:]:
                value = fold.get(key)
                valid = _nonnegative_integer(value) if key in {"mask_intersection_count", "mask_union_count"} else _finite_number(value) and value >= 0
                if not valid:
                    checks.append(_invalid(f"invalid_fold_{index}_{key}", value))
                    invalid_fold_keys.add(key)

            if not {"mask_intersection_count", "mask_union_count"} & invalid_fold_keys:
                numerator = fold["mask_intersection_count"]
                denominator = fold["mask_union_count"]
                if denominator == 0:
                    checks.append(_invalid(f"invalid_fold_{index}_mask_union_count", denominator))
                else:
                    gate = f"fold_{index}_mask_iou_minimum"
                    limit = AUTOMATIC_ACCEPTANCE_THRESHOLDS["fold_mask_iou_minimum"]
                    observed = numerator / denominator
                    checks.append(
                        _check(gate, observed, ">=", limit, observed >= limit,
                               numerator=numerator, denominator=denominator)
                    )
            for metric, threshold in (
                ("boundary_distance_mean_pixels", "fold_boundary_distance_mean_pixels_maximum"),
                ("boundary_distance_p95_pixels", "fold_boundary_distance_p95_pixels_maximum"),
            ):
                if metric in invalid_fold_keys:
                    continue
                gate = f"fold_{index}_{metric}_maximum"
                observed = fold[metric]
                limit = AUTOMATIC_ACCEPTANCE_THRESHOLDS[threshold]
                checks.append(_check(gate, observed, "<=", limit, observed <= limit))

    failed = [row["gate"] for row in checks if not row["passed"]]
    return {
        "schema": AUTOMATIC_ACCEPTANCE_SCHEMA,
        "thresholds": dict(AUTOMATIC_ACCEPTANCE_THRESHOLDS),
        "checks": checks,
        "status": "pass" if not failed else "fail",
        "failed_gates": failed,
    }


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH:
        raise ValueError(f"{label} must be a lowercase SHA-256")
    if any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _canonical_hash_inventory(values: Mapping[str, str], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in values.items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or not name:
            raise ValueError(f"{label} names must be nonempty relative paths")
        result[name] = _require_sha256(value, f"{label}[{name!r}]")
    return dict(sorted(result.items()))


def canonical_acceptance_payload(
    *,
    identity: Mapping[str, object],
    sources: Sequence[Mapping[str, object]],
    metrics: Mapping[str, object],
    fold_metrics: Sequence[Mapping[str, object]],
    artifact_sha256: Mapping[str, str],
    code_sha256: Mapping[str, str],
    finalized_mask_sha256: str,
) -> dict[str, object]:
    """Build path- and run-time-independent automatic acceptance evidence."""
    canonical_identity: dict[str, object] = {}
    for key in _IDENTITY_KEYS:
        if key not in identity:
            raise ValueError(f"missing identity value: {key}")
        canonical_identity[key] = identity[key]
    for key in ("source_id", "camera_id", "installation_id", "orientation"):
        value = canonical_identity[key]
        if not isinstance(value, str) or SAFE_IDENTIFIER.fullmatch(value) is None:
            raise ValueError(f"{key} must match [A-Za-z0-9][A-Za-z0-9._-]*")
    canonical_identity["detector_signature_sha256"] = _require_sha256(
        canonical_identity["detector_signature_sha256"], "detector_signature_sha256"
    )

    canonical_sources: list[dict[str, object]] = []
    for source in sources:
        source_sha256 = _require_sha256(source.get("source_sha256"), "source_sha256")
        observed_bytes = source.get("observed_bytes")
        if not _nonnegative_integer(observed_bytes) or observed_bytes == 0:
            raise ValueError("observed_bytes must be a positive integer")
        canonical_sources.append(
            {"source_sha256": source_sha256, "observed_bytes": observed_bytes}
        )
    canonical_sources.sort(key=lambda row: (row["source_sha256"], row["observed_bytes"]))

    canonical_metrics = {key: metrics.get(key) for key in _METRIC_KEYS}
    canonical_folds = [
        {key: fold.get(key) for key in _FOLD_KEYS}
        for fold in fold_metrics
    ]
    canonical_folds.sort(key=lambda row: row["fold_index"])
    evaluation = evaluate_automatic_gates(canonical_metrics, canonical_folds)
    if evaluation["status"] != "pass":
        raise ValueError(
            "automatic acceptance payload requires passing gates: "
            + ", ".join(evaluation["failed_gates"])
        )

    return {
        "schema": AUTOMATIC_ACCEPTANCE_SCHEMA,
        "identity": canonical_identity,
        "sources": canonical_sources,
        "metrics": canonical_metrics,
        "fold_metrics": canonical_folds,
        "thresholds": dict(AUTOMATIC_ACCEPTANCE_THRESHOLDS),
        "gate_evaluation": evaluation,
        "artifact_sha256": _canonical_hash_inventory(artifact_sha256, "artifact_sha256"),
        "code_sha256": _canonical_hash_inventory(code_sha256, "code_sha256"),
        "finalized_mask_sha256": _require_sha256(
            finalized_mask_sha256, "finalized_mask_sha256"
        ),
    }


def canonical_json_sha256(payload: Mapping[str, object]) -> str:
    """Hash one mapping using canonical compact UTF-8 JSON."""
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_automatic_acceptance(
    payload: object,
    *,
    expected_identity: Mapping[str, object] | None = None,
    expected_finalized_mask_sha256: str | None = None,
) -> dict[str, object]:
    """Strictly validate and canonicalize one automatic acceptance record."""
    if not isinstance(payload, dict):
        raise ValueError("automatic acceptance must be a JSON object")
    try:
        rebuilt = canonical_acceptance_payload(
            identity=payload["identity"],
            sources=payload["sources"],
            metrics=payload["metrics"],
            fold_metrics=payload["fold_metrics"],
            artifact_sha256=payload["artifact_sha256"],
            code_sha256=payload["code_sha256"],
            finalized_mask_sha256=payload["finalized_mask_sha256"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid automatic acceptance: {exc}") from exc
    if payload != rebuilt:
        raise ValueError("automatic acceptance is not the exact canonical schema")
    if expected_identity is not None:
        for name, expected in expected_identity.items():
            if rebuilt["identity"].get(name) != expected:
                raise ValueError(f"automatic acceptance identity mismatch: {name}")
    if expected_finalized_mask_sha256 is not None:
        expected = _require_sha256(
            expected_finalized_mask_sha256, "expected_finalized_mask_sha256"
        )
        if rebuilt["finalized_mask_sha256"] != expected:
            raise ValueError("automatic acceptance finalized mask mismatch")
    return rebuilt


def automatic_mask_id(
    installation_id: str, mask_sha256: str, acceptance_sha256: str
) -> str:
    """Return a deterministic safe identifier binding mask and evidence."""
    if not isinstance(installation_id, str) or SAFE_IDENTIFIER.fullmatch(installation_id) is None:
        raise ValueError("installation_id must match [A-Za-z0-9][A-Za-z0-9._-]*")
    mask_hash = _require_sha256(mask_sha256, "mask_sha256")
    acceptance_hash = _require_sha256(acceptance_sha256, "acceptance_sha256")
    return f"{installation_id}-auto-{mask_hash[:12]}-{acceptance_hash[:12]}"


def atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    """Publish JSON atomically without exposing an incomplete destination."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                payload,
                stream,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
