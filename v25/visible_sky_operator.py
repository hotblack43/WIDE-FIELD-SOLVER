#!/usr/bin/env python3
"""Operate the v25 visible-sky calibration lifecycle from one TOML file."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
import sys
import tomllib
from typing import Sequence

from scripts.build_visible_sky_mask import main as builder_main
from visible_sky_auto_workflow import (
    AutomaticWorkflowConfig,
    run_automatic_workflow,
)
from visible_sky_acquisition import acquire_managed_calibration_inputs
from visible_sky_calibration import draft_filename
from visible_sky_registry import load_registry


SCHEMA = "wide-field-solver-visible-sky-operator-v1"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
AUTOMATIC_ORIENTATION = "detector_native_top_left_xy_right_y_down"
CONFIG_KEYS = {
    "schema",
    "source_id",
    "camera_id",
    "installation_id",
    "orientation",
    "download_manifest",
    "archive_root",
    "review_root",
    "calibration_root",
}
IDENTIFIER_KEYS = ("source_id", "camera_id", "installation_id", "orientation")
PATH_KEYS = (
    "download_manifest",
    "archive_root",
    "review_root",
    "calibration_root",
)


@dataclass(frozen=True)
class OperatorConfig:
    path: Path
    source_id: str
    camera_id: str
    installation_id: str
    orientation: str
    download_manifest: Path
    archive_root: Path
    review_root: Path
    calibration_root: Path

    @classmethod
    def load(cls, path: Path) -> "OperatorConfig":
        source = Path(path).expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError(f"visible-sky configuration is not a file: {source}")
        with source.open("rb") as stream:
            payload = tomllib.load(stream)
        if set(payload) != CONFIG_KEYS:
            missing = sorted(CONFIG_KEYS - set(payload))
            unknown = sorted(set(payload) - CONFIG_KEYS)
            raise ValueError(
                "invalid visible-sky configuration keys: "
                f"missing={missing}, unknown={unknown}"
            )
        if payload.get("schema") != SCHEMA:
            raise ValueError("unsupported visible-sky operator configuration schema")
        identifiers = {}
        for key in IDENTIFIER_KEYS:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"visible-sky configuration {key} must be non-empty")
            identifiers[key] = value.strip()
        draft_filename(identifiers["installation_id"])
        resolved_paths = {}
        for key in PATH_KEYS:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"visible-sky configuration {key} must be a path")
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = source.parent / candidate
            resolved_paths[key] = candidate.resolve()
        if not resolved_paths["download_manifest"].is_file():
            raise ValueError(
                "download_manifest is not a file: "
                f"{resolved_paths['download_manifest']}"
            )
        if not resolved_paths["archive_root"].is_dir():
            raise ValueError(
                f"archive_root is not a directory: {resolved_paths['archive_root']}"
            )
        return cls(source, **identifiers, **resolved_paths)


def discover_automatic_workflow_configs(
    repository_root: Path,
) -> tuple[AutomaticWorkflowConfig, ...]:
    """Find managed camera populations that already meet the data-count gates."""
    root = Path(repository_root).expanduser().resolve()
    archive_root = (root / "raw_allsky_samples").resolve(strict=True)
    manifest = (archive_root / "manifest.sqlite").resolve(strict=True)
    uri = f"{manifest.as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            """
            SELECT source_id, camera_id, observed_utc
            FROM downloads
            WHERE download_status='downloaded'
              AND validation_status='verified'
            ORDER BY source_id, camera_id, observed_utc
            """
        ).fetchall()
    populations: dict[tuple[str, str], dict[str, int]] = {}
    for source_id, camera_id, observed_utc in rows:
        try:
            date = datetime.fromisoformat(
                str(observed_utc).replace("Z", "+00:00")
            ).date().isoformat()
        except ValueError as exc:
            raise ValueError(
                f"invalid observed_utc for {source_id}/{camera_id}: {observed_utc!r}"
            ) from exc
        dates = populations.setdefault((str(source_id), str(camera_id)), {})
        dates[date] = dates.get(date, 0) + 1

    calibrated = registered_camera_keys(root)

    configs = []
    for (source_id, camera_id), date_counts in sorted(populations.items()):
        if (source_id, camera_id) in calibrated:
            continue
        dates = sorted(date_counts)
        held_out = dates[0::5]
        calibration = [date for index, date in enumerate(dates) if index % 5]
        held_out_sources = sum(date_counts[date] for date in held_out)
        if (
            len(dates) < 10
            or len(calibration) < 8
            or len(held_out) < 2
            or held_out_sources < 20
        ):
            continue
        configs.append(
            AutomaticWorkflowConfig(
                source_id=source_id,
                camera_id=camera_id,
                installation_id=f"{source_id}-{camera_id}-automatic",
                orientation=AUTOMATIC_ORIENTATION,
                download_manifest=manifest,
                archive_root=archive_root,
                review_root=root / "calibration-review",
                calibration_root=root / "camera-calibrations",
            )
        )
    return tuple(configs)


def registered_camera_keys(
    repository_root: Path,
) -> frozenset[tuple[str, str]]:
    """Return bundled calibrations and explicitly activated managed cameras."""
    root = Path(repository_root).expanduser().resolve()
    bundled_registry = root / "v25/data/sky_masks/registry.jsonl"
    managed_registry = root / "camera-calibrations/registry.jsonl"
    calibrated: set[tuple[str, str]] = set()
    if bundled_registry.is_file():
        calibrated.update(
            (str(record["source_id"]), str(record["camera_id"]))
            for record in load_registry((bundled_registry,))
            if record["record_type"] == "calibration"
        )
    if managed_registry.is_file():
        calibrated.update(
            (str(record["source_id"]), str(record["camera_id"]))
            for record in load_registry((managed_registry,))
            if record["record_type"] == "activation"
        )
    return frozenset(calibrated)


def delegate_arguments(
    command: str, config: OperatorConfig, args: argparse.Namespace
) -> list[str]:
    if command == "propose":
        output = args.output or config.review_root / config.installation_id
        return [
            "propose",
            "--download-manifest", str(config.download_manifest),
            "--archive-root", str(config.archive_root),
            "--source", config.source_id,
            "--camera", config.camera_id,
            "--installation-id", config.installation_id,
            "--orientation", config.orientation,
            "--output", str(Path(output).expanduser().resolve()),
        ]
    if command == "revise":
        return [
            "revise",
            "--parent-selection", str(args.parent_selection),
            "--edited-mask", str(args.edited_mask),
            "--output", str(args.output),
        ]
    if command == "approve":
        return [
            "approve",
            "--proposal", str(args.proposal),
            "--reviewed-draft-sha256", args.reviewed_draft_sha256,
            "--mask-id", args.mask_id,
            "--approved-by", args.approved_by,
            "--safety-margin-pixels", str(args.safety_margin_pixels),
            "--calibration-root", str(config.calibration_root),
        ]
    if command == "activate":
        return [
            "activate",
            "--calibration-registry", str(config.calibration_root / "registry.jsonl"),
            "--source", config.source_id,
            "--camera", config.camera_id,
            "--installation-id", config.installation_id,
        ]
    raise ValueError(f"unknown visible-sky operator command: {command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    auto = commands.add_parser(
        "auto", help="validate, approve, register, and activate one camera mask"
    )
    auto.add_argument(
        "--config",
        type=Path,
        help="advanced override; default discovers eligible managed cameras",
    )
    auto.add_argument(
        "--replace-active",
        action="store_true",
        help="allow activation to replace a different active installation after validation",
    )
    propose = commands.add_parser("propose", help="create one review-only proposal")
    propose.add_argument("--config", type=Path, required=True)
    propose.add_argument("--output", type=Path)
    revise = commands.add_parser("revise", help="write an immutable corrected proposal")
    revise.add_argument("--config", type=Path, required=True)
    revise.add_argument("--parent-selection", type=Path, required=True)
    revise.add_argument("--edited-mask", type=Path, required=True)
    revise.add_argument("--output", type=Path, required=True)
    approve = commands.add_parser("approve", help="approve one exact reviewed draft")
    approve.add_argument("--config", type=Path, required=True)
    approve.add_argument("--proposal", type=Path, required=True)
    approve.add_argument("--reviewed-draft-sha256", required=True)
    approve.add_argument("--mask-id", required=True)
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--safety-margin-pixels", type=int, default=5)
    activate = commands.add_parser(
        "activate", help="activate the approved installation for future downloads"
    )
    activate.add_argument("--config", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ["auto"]
    args = build_parser().parse_args(arguments)
    if args.command == "auto":
        try:
            if args.config is None:
                calibrated = registered_camera_keys(REPOSITORY_ROOT)
                acquisition = acquire_managed_calibration_inputs(
                    REPOSITORY_ROOT, calibrated
                )
                workflow_configs = discover_automatic_workflow_configs(
                    REPOSITORY_ROOT
                )
            else:
                acquisition = None
                config = OperatorConfig.load(args.config)
                workflow_configs = (
                    AutomaticWorkflowConfig(
                        source_id=config.source_id,
                        camera_id=config.camera_id,
                        installation_id=config.installation_id,
                        orientation=config.orientation,
                        download_manifest=config.download_manifest,
                        archive_root=config.archive_root,
                        review_root=config.review_root,
                        calibration_root=config.calibration_root,
                    ),
                )
        except (OSError, ValueError, sqlite3.Error) as exc:
            message = " ".join(str(exc).splitlines())
            print(f"NOT ACTIVATED status=configuration_error error={message}")
            return 2
        if not workflow_configs:
            if acquisition is not None and acquisition.failed_requests:
                print(
                    "NOT ACTIVATED status=acquisition_failure "
                    f"failed_requests={acquisition.failed_requests}"
                )
                return 2
            if acquisition is not None and acquisition.attempted_requests:
                print(
                    "ACQUIRING calibration images remain below the automatic threshold"
                )
                return 0
            print("UP TO DATE no uncalibrated managed camera has enough data")
            return 0
        results = tuple(
            run_automatic_workflow(config, replace_active=args.replace_active)
            for config in workflow_configs
        )
        if len(results) == 1:
            result = results[0]
            if result.status == "activated":
                print(
                    f"ACTIVATED manifest={result.manifest_path} "
                    f"inspection={result.run_root / 'primary/boundary_review.png'} "
                    f"receipt={result.receipt_path}"
                )
            else:
                print(
                    f"NOT ACTIVATED status={result.status} "
                    f"receipt={result.receipt_path}"
                )
            return result.exit_code
        activated = sum(result.status == "activated" for result in results)
        if activated == len(results):
            print(
                f"ACTIVATED cameras={activated} "
                f"calibration_root={workflow_configs[0].calibration_root}"
            )
            return 0
        exit_code = max(result.exit_code for result in results)
        print(
            f"NOT ACTIVATED status=batch_incomplete activated={activated} "
            f"cameras={len(results)} review_root={workflow_configs[0].review_root}"
        )
        return exit_code
    try:
        config = OperatorConfig.load(args.config)
    except (OSError, ValueError):
        raise
    return builder_main(delegate_arguments(args.command, config, args))


if __name__ == "__main__":
    raise SystemExit(main())
