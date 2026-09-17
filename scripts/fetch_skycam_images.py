#!/usr/bin/env python3
"""Periodically download the Subaru Maunakea all-sky image."""

from __future__ import annotations

import argparse
import math
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Sequence
from threading import TIMEOUT_MAX
from typing import TextIO
from urllib.request import Request, urlopen


DEFAULT_INTERVAL_MINUTES = 20.0
DEFAULT_OUTPUT_DIR = Path("skycam-images")
IMAGE_URL = "https://www.ncsm.city.nagoya.jp/astro/subaru/NOW-dm.jpg"
REQUEST_TIMEOUT_SECONDS = 30
MAX_IMAGE_BYTES = 64 * 1024 * 1024
USER_AGENT = "wide-field-solver-skycam/1.0"


class DownloadError(RuntimeError):
    """The remote response is not a usable all-sky JPEG."""


@dataclass(frozen=True)
class Config:
    """Validated command-line configuration."""

    interval_minutes: float
    output_dir: Path
    once: bool


def positive_finite_minutes(value: str) -> float:
    """Parse a strictly positive, finite minute interval."""

    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    interval_seconds = number * 60.0
    if not math.isfinite(interval_seconds) or interval_seconds > TIMEOUT_MAX:
        raise argparse.ArgumentTypeError("interval is too large for this platform")
    return number


def parse_args(argv: Sequence[str] | None = None) -> Config:
    """Parse command-line arguments into a stable configuration object."""

    parser = argparse.ArgumentParser(
        description="Periodically download the Subaru Maunakea all-sky image."
    )
    parser.add_argument(
        "--interval-minutes",
        type=positive_finite_minutes,
        default=DEFAULT_INTERVAL_MINUTES,
        help="minutes between attempts (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="directory for downloaded images (default: %(default)s)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="download once and exit instead of running continuously",
    )
    args = parser.parse_args(argv)
    return Config(args.interval_minutes, args.output_dir, args.once)


def capture_path(output_dir: Path, acquired_at: datetime) -> Path:
    """Return an unused UTC-timestamped destination path."""

    stamp = acquired_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = output_dir / f"subaru_maunakea_{stamp}.jpg"
    suffix = 1
    while os.path.lexists(candidate):
        candidate = output_dir / f"subaru_maunakea_{stamp}_{suffix}.jpg"
        suffix += 1
    return candidate


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""

    return datetime.now(timezone.utc)


def download_once(
    output_dir: Path,
    *,
    opener=urlopen,
    now=utc_now,
) -> Path:
    """Download, validate, and atomically publish one all-sky JPEG."""

    output_dir.mkdir(parents=True, exist_ok=True)
    request = Request(IMAGE_URL, headers={"User-Agent": USER_AGENT})
    with opener(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        content_type = (
            response.headers.get("Content-Type", "")
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        body = response.read(MAX_IMAGE_BYTES + 1)

    if len(body) > MAX_IMAGE_BYTES:
        raise DownloadError(f"response exceeds {MAX_IMAGE_BYTES}-byte limit")
    if content_type != "image/jpeg":
        received = content_type or "no Content-Type"
        raise DownloadError(f"expected image/jpeg, received {received}")
    if not body.startswith(b"\xff\xd8") or not body.endswith(b"\xff\xd9"):
        raise DownloadError("response is not a complete JPEG")

    acquired_at = now()
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_dir,
            prefix=".subaru_maunakea_",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())

        while True:
            destination = capture_path(output_dir, acquired_at)
            try:
                os.link(temp_path, destination)
                return destination
            except FileExistsError:
                continue
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def run(
    config: Config,
    *,
    downloader=download_once,
    monotonic=time.monotonic,
    sleep=time.sleep,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run one download or continue attempting on a monotonic schedule."""

    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    interval_seconds = config.interval_minutes * 60.0
    scheduled_start = monotonic()

    while True:
        try:
            saved = downloader(config.output_dir)
            print(f"Saved {saved}", file=stdout, flush=True)
        except Exception as exc:
            print(f"Download failed: {exc}", file=stderr, flush=True)
            if config.once:
                return 1

        if config.once:
            return 0

        next_start = scheduled_start + interval_seconds
        current = monotonic()
        if next_start < current:
            next_start = current
        sleep(max(0.0, next_start - current))
        scheduled_start = next_start


def main(
    argv: Sequence[str] | None = None,
    *,
    runner=run,
    stderr: TextIO | None = None,
) -> int:
    """Run the command-line program and return its process exit status."""

    stderr = sys.stderr if stderr is None else stderr
    config = parse_args(argv)
    try:
        return runner(config)
    except KeyboardInterrupt:
        print("Stopped.", file=stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
