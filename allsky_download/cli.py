from __future__ import annotations

import argparse
from datetime import date
import logging
import math
from pathlib import Path, PurePath
from typing import Sequence

from .cadence import parse_duration, select_candidates, site_date_range
from .http import HttpClient, TransferError
from .manifest import Manifest, OutputLockedError, output_lock
from .model import Candidate
from .registry import SourceRegistry


LOG = logging.getLogger(__name__)
DEFAULT_OUTPUT = Path("raw_allsky_samples")
DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "sources.json"


def _date_value(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def _nonnegative_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an integer") from exc
    if value < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return value


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a number") from exc
    if value <= 0 or not math.isfinite(value):
        raise argparse.ArgumentTypeError("must be positive and finite")
    return value


def _duration_value(text: str) -> str:
    try:
        parse_duration(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return text


class _ArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        result = super().parse_args(args, namespace)
        if result.date is not None and result.end is not None:
            self.error("--end cannot be combined with --date")
        if result.start is not None and result.end is None:
            self.error("--start requires --end")
        if result.end is not None and result.start is None:
            self.error("--end requires --start")
        return result


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        description=(
            "List and safely download cadence-selected original high-dynamic-range "
            "all-sky files."
        )
    )
    parser.add_argument("--site", required=True, help="source ID or alias")
    parser.add_argument(
        "--camera", action="append", help="camera ID; repeat for multiple cameras"
    )
    period = parser.add_mutually_exclusive_group(required=True)
    period.add_argument("--date", type=_date_value, help="one site-local civil day")
    period.add_argument("--start", type=_date_value, help="first site-local date")
    parser.add_argument("--end", type=_date_value, help="exclusive site-local end date")
    parser.add_argument("--cadence", type=_duration_value, default="10m")
    parser.add_argument("--max-files", type=_positive_int, default=20)
    parser.add_argument(
        "--latest",
        action="store_true",
        help="select the newest cadence slots (intended for incremental cron runs)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=_positive_float, default=45.0)
    parser.add_argument("--retries", type=_nonnegative_int, default=3)
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def _safe_filename(candidate: Candidate) -> str:
    filename = candidate.filename
    path = PurePath(filename)
    if (
        not filename
        or filename in {".", ".."}
        or path.is_absolute()
        or "/" in filename
        or "\\" in filename
    ):
        raise ValueError(f"unsafe remote filename: {filename!r}")
    return filename


def _iso_z(candidate: Candidate) -> str:
    return candidate.observed_at.isoformat().replace("+00:00", "Z")


def _print_selection(selection) -> None:
    for item in selection.candidates:
        size = str(item.size_bytes) if item.size_bytes is not None else "unknown"
        print(
            "\t".join(
                (
                    "SELECT",
                    _iso_z(item),
                    item.source_id,
                    item.camera_id,
                    item.filename,
                    size,
                    item.url,
                )
            )
        )
    print(
        "\t".join(
            (
                "SUMMARY",
                f"selected={len(selection.candidates)}",
                f"eligible={selection.eligible_count}",
                f"truncated={str(selection.truncated).lower()}",
                f"known_bytes={selection.known_bytes}",
                f"unknown_sizes={selection.unknown_size_count}",
            )
        )
    )


def _resolve_sites(adapter, camera_ids: list[str] | None):
    if not camera_ids:
        return adapter.sites(None)
    resolved = []
    seen = set()
    for camera_id in camera_ids:
        for site in adapter.sites(camera_id):
            key = (site.source_id, site.camera_id)
            if key not in seen:
                resolved.append(site)
                seen.add(key)
    return tuple(resolved)


def _destination(output: Path, candidate: Candidate) -> Path:
    return output / candidate.source_id / candidate.camera_id / _safe_filename(candidate)


def run(
    args: argparse.Namespace,
    *,
    registry: SourceRegistry | None = None,
    client: HttpClient | None = None,
) -> int:
    registry = registry or SourceRegistry.from_json(DEFAULT_REGISTRY)
    client = client or HttpClient(timeout=args.timeout, retries=args.retries)
    try:
        source_id = registry.resolve_source_id(args.site)
        adapter = registry.get_adapter(source_id)
        sites = _resolve_sites(adapter, args.camera)
        ranges = {
            (site.source_id, site.camera_id): site_date_range(
                site, date_value=args.date, start=args.start, end=args.end
            )
            for site in sites
        }
        candidates = []
        for site in sites:
            candidates.extend(adapter.list_candidates(client, site, ranges[(site.source_id, site.camera_id)]))
        selection = select_candidates(
            candidates,
            ranges,
            parse_duration(args.cadence),
            args.max_files,
            newest=args.latest,
        )
        _print_selection(selection)
        if args.dry_run:
            return 0

        destinations: dict[Path, str] = {}
        for candidate in selection.candidates:
            path = _destination(args.output, candidate)
            other_url = destinations.setdefault(path, candidate.url)
            if other_url != candidate.url:
                raise ValueError(
                    f"two remote objects map to the same local path: {path}"
                )

        failed = False
        with output_lock(args.output):
            with Manifest(args.output / "manifest.sqlite") as manifest:
                for candidate in selection.candidates:
                    existing = manifest.verified_download(candidate, args.output)
                    if existing is not None:
                        print(f"REUSE\t{candidate.url}\t{existing.path}")
                        continue
                    manifest.record_attempt(candidate)
                    try:
                        downloaded = client.download_atomic(
                            candidate, _destination(args.output, candidate)
                        )
                        manifest.record_success(candidate, downloaded, args.output)
                        print(
                            f"DOWNLOAD\t{candidate.url}\t{downloaded.path}\t"
                            f"{downloaded.size_bytes}\t{downloaded.sha256}"
                        )
                    except Exception as exc:
                        failed = True
                        manifest.record_failure(candidate, str(exc))
                        LOG.error("download failed for %s: %s", candidate.url, exc)
        return 2 if failed else 0
    except KeyboardInterrupt:
        return 130
    except (OutputLockedError, OSError, TransferError, ValueError) as exc:
        LOG.error("all-sky download failed: %s", exc)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run(args)
