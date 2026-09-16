#!/usr/bin/env python3
"""Build or verify v6's metadata-independent builtin planet reference."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from point_star_planet_ephemeris import load_ephemeris  # noqa: E402


def verify(path: Path) -> dict:
    try:
        with np.load(path, allow_pickle=False) as data:
            provenance = json.loads(str(data['provenance']))
        _, _, checked = load_ephemeris(
            float(provenance['start_jyear']), float(provenance['end_jyear']),
            bundled_path=path)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ValueError(f'invalid ephemeris {path}: {exc}') from exc
    return checked


def build(path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='planet-ephemeris-') as temporary:
        _, _, generated = load_ephemeris(
            1850., 2036., cache_dir=temporary, prefer_bundled=False)
        source = Path(generated['cache_path'])
        staging = path.with_name('.'+path.name+'.tmp')
        shutil.copy2(source, staging)
        staging.replace(path)
    return verify(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--output', type=Path)
    action.add_argument('--verify', type=Path)
    args = parser.parse_args(argv)
    try:
        provenance = build(args.output) if args.output else verify(args.verify)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"valid planet reference: {provenance['content_sha256']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
