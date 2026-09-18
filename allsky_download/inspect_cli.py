from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .inspect import write_inspection


SUFFIXES = (".fits", ".fit", ".fts", ".fits.bz2", ".fit.bz2", ".fts.bz2", ".h5", ".hdf5", ".cr2", ".cr3", ".nef", ".dng", ".arw")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect genuine scientific all-sky originals without rewriting them.")
    parser.add_argument("--root", type=Path, default=Path("raw_allsky_samples"))
    parser.add_argument("--output", type=Path, default=Path("raw_allsky_samples/inspection.json"))
    parser.add_argument("--preview-dir", type=Path, default=Path("raw_allsky_samples/derived/inspection"))
    return parser


def _originals(root: Path) -> list[Path]:
    paths = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if not path.is_file() or relative.parts[0] == "derived":
            continue
        lowered = path.name.lower()
        if lowered.endswith(SUFFIXES):
            paths.append(path)
    return sorted(paths)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = _originals(args.root)
    if not paths:
        raise SystemExit(f"no supported originals beneath {args.root}")
    records = write_inspection(paths, args.output, args.preview_dir)
    for record in records:
        print(f"INSPECT\t{record['format']}\t{record['path']}\t{record['inspection_id']}")
    print(f"SUMMARY\trecords={len(records)}\toutput={args.output}")
    return 0
