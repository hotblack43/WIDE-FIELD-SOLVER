#!/usr/bin/env python3
"""Summarize MMTO FITS humidity telemetry and plot its observed distribution."""
from __future__ import annotations

import argparse
import bz2
import csv
from collections import Counter
import json
import math
from pathlib import Path
from typing import Iterable, Sequence

from astropy.io import fits
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


FITS_BLOCK_BYTES = 2880
FITS_CARD_BYTES = 80


def read_primary_header(path: Path) -> fits.Header:
    """Read only the primary FITS header from a bzip2-compressed image."""
    cards: list[bytes] = []
    with bz2.open(path, "rb") as stream:
        while True:
            block = stream.read(FITS_BLOCK_BYTES)
            if len(block) != FITS_BLOCK_BYTES:
                raise OSError("compressed FITS ended before the primary header END card")
            for offset in range(0, FITS_BLOCK_BYTES, FITS_CARD_BYTES):
                card = block[offset:offset + FITS_CARD_BYTES]
                cards.append(card)
                if card[:8].strip() == b"END":
                    text = b"".join(cards).decode("ascii")
                    return fits.Header.fromstring(text, sep="")


def classify_humidity(raw_value: object) -> tuple[str, float | None]:
    """Classify header telemetry without treating unavailable data as weather."""
    if raw_value is None:
        return "missing", None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return "invalid", None
    if not math.isfinite(value) or value < 0.0 or value > 100.0:
        return "invalid", None
    if value == 0.0:
        return "zero_placeholder", None
    return "valid", value


def collect_humidity_records(paths: Iterable[Path]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in paths:
        record: dict[str, object] = {
            "path": str(path),
            "date_obs": "",
            "humidity_raw": "",
            "humidity_percent": None,
            "status": "unreadable",
            "error": "",
        }
        try:
            header = read_primary_header(path)
            raw_value = header.get("HUMIDITY")
            status, value = classify_humidity(raw_value)
            record.update({
                "date_obs": str(header.get("DATE-OBS", "")),
                "humidity_raw": "" if raw_value is None else str(raw_value),
                "humidity_percent": value,
                "status": status,
            })
        except (OSError, EOFError, UnicodeDecodeError, ValueError) as error:
            record["error"] = f"{type(error).__name__}: {error}"
        records.append(record)
    return records


def summarize(records: Sequence[dict[str, object]]) -> dict[str, object]:
    counts = Counter(str(record["status"]) for record in records)
    values = np.asarray([
        float(record["humidity_percent"])
        for record in records
        if record["status"] == "valid"
    ], dtype=float)
    result: dict[str, object] = {
        "total_files": len(records),
        "status_counts": {
            status: counts.get(status, 0)
            for status in ("valid", "zero_placeholder", "missing", "invalid", "unreadable")
        },
    }
    if values.size:
        result["valid_humidity_percent"] = {
            "minimum": float(np.min(values)),
            "p10": float(np.percentile(values, 10)),
            "p25": float(np.percentile(values, 25)),
            "median": float(np.median(values)),
            "p75": float(np.percentile(values, 75)),
            "p90": float(np.percentile(values, 90)),
            "maximum": float(np.max(values)),
        }
    else:
        result["valid_humidity_percent"] = None
    return result


def write_csv(path: Path, records: Sequence[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "path", "date_obs", "humidity_raw", "humidity_percent", "status", "error"
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def plot_histogram(
    path: Path,
    records: Sequence[dict[str, object]],
    summary: dict[str, object],
) -> None:
    values = np.asarray([
        float(record["humidity_percent"])
        for record in records
        if record["status"] == "valid"
    ], dtype=float)
    counts = summary["status_counts"]
    assert isinstance(counts, dict)

    figure, axis = plt.subplots(figsize=(10.5, 6.5), constrained_layout=True)
    bins = np.arange(0.0, 102.0, 2.0)
    axis.hist(values, bins=bins, color="#2878B5", edgecolor="white", linewidth=0.6)
    axis.set_xlim(0.0, 100.0)
    axis.set_xlabel("External relative humidity recorded in FITS header (%)")
    axis.set_ylabel("Number of MMTO sky-camera images")
    axis.set_title(
        "Observed MMTO humidity distribution\n"
        "Local FITS archive; zero placeholders and unavailable telemetry excluded"
    )
    axis.grid(axis="y", alpha=0.25)

    statistics = summary["valid_humidity_percent"]
    if isinstance(statistics, dict):
        median = float(statistics["median"])
        axis.axvline(
            median,
            color="#D95319",
            linestyle="--",
            linewidth=1.8,
            label=f"median = {median:.1f}%",
        )
        axis.legend(frameon=False, loc="upper left")

    annotation = (
        f"Files: {summary['total_files']:,}\n"
        f"Valid RH: {counts['valid']:,}\n"
        f"Zero placeholders: {counts['zero_placeholder']:,}\n"
        f"Missing: {counts['missing']:,}\n"
        f"Invalid/unreadable: {counts['invalid'] + counts['unreadable']:,}"
    )
    axis.text(
        0.985,
        0.965,
        annotation,
        transform=axis.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "alpha": 0.9,
              "edgecolor": "0.75"},
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=180, metadata={
        "Title": "Observed MMTO humidity distribution",
        "Description": "Histogram of valid positive HUMIDITY FITS-header readings.",
    })
    plt.close(figure)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    paths = sorted(args.archive.rglob("*.fits.bz2"))
    records = collect_humidity_records(paths)
    summary = summarize(records)
    write_csv(args.csv, records)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    plot_histogram(args.output, records, summary)
    print(
        "MMTO_HUMIDITY "
        f"files={summary['total_files']} "
        + " ".join(
            f"{status}={count}"
            for status, count in summary["status_counts"].items()
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
