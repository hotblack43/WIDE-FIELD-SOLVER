"""V26 opt-in calibration assignment around the frozen downloader CLI."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
from types import MethodType
from typing import Sequence

import allsky_download.cli as frozen_cli
from allsky_download.http import HttpClient
from allsky_download.registry import SourceRegistry

from .manifest import Manifest


LOG = logging.getLogger(__name__)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = frozen_cli.build_parser()
    parser.add_argument(
        "--calibration-registry", type=Path,
        help="append-only approved-calibration registry for assignment at ingest",
    )
    parser.add_argument(
        "--installation-assignments", type=Path,
        help="append-only source-checksum assignment registry",
    )
    parser.add_argument(
        "--camera-orientation",
        help="declared detector orientation used by the approved calibration",
    )
    frozen_parse_args = parser.parse_args

    def parse_args(self, args=None, namespace=None):
        result = frozen_parse_args(args, namespace)
        calibration = (
            result.calibration_registry,
            result.installation_assignments,
            result.camera_orientation,
        )
        if any(value is not None for value in calibration) and not all(
            value is not None for value in calibration
        ):
            self.error(
                "--calibration-registry, --installation-assignments, and "
                "--camera-orientation must be supplied together"
            )
        return result

    parser.parse_args = MethodType(parse_args, parser)
    return parser


def build_assign_existing_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="allsky-download-v26 assign-existing",
        description=(
            "Preview or explicitly assign a bounded set of existing verified "
            "downloads to the active approved camera installation."
        ),
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--camera", required=True)
    parser.add_argument("--limit", type=_positive_int, required=True)
    parser.add_argument("--calibration-registry", type=Path, required=True)
    parser.add_argument("--installation-assignments", type=Path, required=True)
    parser.add_argument("--camera-orientation", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


class _AssignmentFailure(RuntimeError):
    pass


def _configured_manifest_class(args):
    class ConfiguredManifest(Manifest):
        def record_success(
            self, candidate, downloaded, output_root, *, enqueue_processing=False
        ):
            self.record_configured_success(candidate, downloaded, output_root)
            installation_id = None
            try:
                from v26.visible_sky_registry import (
                    active_installation,
                    assign_source,
                )

                active = active_installation(
                    (args.calibration_registry,),
                    source_id=candidate.source_id,
                    camera_id=candidate.camera_id,
                )
                if active is None:
                    raise ValueError(
                        "no active approved installation for "
                        f"{candidate.source_id}/{candidate.camera_id}"
                    )
                installation_id = str(active["installation_id"])
                assignment = assign_source(
                    args.installation_assignments,
                    downloaded.path,
                    downloaded.sha256,
                    source_id=candidate.source_id,
                    camera_id=candidate.camera_id,
                    registry_paths=(args.calibration_registry,),
                    installation_id=installation_id,
                    orientation=args.camera_orientation,
                )
                self.record_assignment_success_and_enqueue(
                    candidate.url, str(assignment["installation_id"]),
                    downloaded.sha256, enqueue_processing=enqueue_processing,
                )
            except Exception as exc:
                self.record_assignment_failure(
                    candidate.url, installation_id, str(exc)
                )
                print(
                    f"UNASSIGNED\t{candidate.url}\t{downloaded.path}\t"
                    f"{downloaded.sha256}\t{exc}"
                )
                raise _AssignmentFailure(
                    f"installation assignment failed: {exc}"
                ) from exc

        def record_failure(self, candidate, error):
            if error.startswith("installation assignment failed: "):
                return
            super().record_failure(candidate, error)

    return ConfiguredManifest


def run(
    args: argparse.Namespace,
    *,
    registry: SourceRegistry | None = None,
    client: HttpClient | None = None,
) -> int:
    if args.calibration_registry is None:
        return frozen_cli.run(args, registry=registry, client=client)
    original_manifest = frozen_cli.Manifest
    configured = _configured_manifest_class(args)
    frozen_cli.Manifest = configured
    try:
        status = frozen_cli.run(args, registry=registry, client=client)
    finally:
        frozen_cli.Manifest = original_manifest
    return status


def run_assign_existing(args: argparse.Namespace) -> int:
    try:
        archive_root = args.archive_root.expanduser().resolve(strict=True)
        if not archive_root.is_dir():
            raise ValueError(f"archive root is not a directory: {archive_root}")
        manifest_path = args.manifest.expanduser().resolve(strict=True)
        try:
            manifest_path.relative_to(archive_root)
        except ValueError as exc:
            raise ValueError(
                f"manifest must be inside archive root {archive_root}: {manifest_path}"
            ) from exc

        from v26.visible_sky_registry import active_installation, assign_source

        active = active_installation(
            (args.calibration_registry,), source_id=args.source, camera_id=args.camera
        )
        if active is None:
            raise ValueError(
                f"no active approved installation for {args.source}/{args.camera}"
            )
        installation_id = str(active["installation_id"])
        failed = False
        with Manifest(manifest_path) as manifest:
            for row in manifest.assignment_candidates(
                args.source, args.camera, args.limit
            ):
                relative = Path(str(row["local_path"]))
                if relative.is_absolute():
                    raise ValueError(
                        f"download manifest local path must be relative: {relative}"
                    )
                source = (archive_root / relative).resolve(strict=True)
                try:
                    source.relative_to(archive_root)
                except ValueError as exc:
                    raise ValueError(
                        f"download path escapes archive root: {relative}"
                    ) from exc
                print(
                    f"ASSIGN_EXISTING\t{row['sha256']}\t{source}\t"
                    f"{installation_id}\tapply={str(args.apply).lower()}"
                )
                if not args.apply:
                    continue
                try:
                    assignment = assign_source(
                        args.installation_assignments,
                        source,
                        str(row["sha256"]),
                        source_id=args.source,
                        camera_id=args.camera,
                        registry_paths=(args.calibration_registry,),
                        installation_id=installation_id,
                        orientation=args.camera_orientation,
                    )
                    manifest.record_assignment_success(
                        str(row["remote_url"]), str(assignment["installation_id"])
                    )
                except Exception as exc:
                    failed = True
                    manifest.record_assignment_failure(
                        str(row["remote_url"]), installation_id, str(exc)
                    )
                    LOG.error(
                        "historical installation assignment failed for %s: %s",
                        row["remote_url"], exc,
                    )
        return 2 if failed else 0
    except (OSError, ValueError) as exc:
        LOG.error("assign-existing failed: %s", exc)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "assign-existing":
        parser = build_assign_existing_parser()
        args = parser.parse_args(arguments[1:])
    else:
        parser = build_parser()
        args = parser.parse_args(arguments)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if arguments and arguments[0] == "assign-existing":
        return run_assign_existing(args)
    return run(args)
