#!/usr/bin/env python3
"""Run the v12 nested radial-model study over saved point-source solutions."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


PACKAGE = Path(__file__).resolve().parents[1]
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

from radial_study import run_batch


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("solutions", nargs="+", type=Path)
    command.add_argument("--catalogue", action="append", type=Path, default=[])
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--workers", type=int, default=1)
    command.add_argument("--max-order", type=int, default=5)
    command.add_argument("--fold-count", type=int, default=8)
    command.add_argument("--bootstrap-replicates", type=int, default=10_000)
    command.add_argument("--seed", type=int, default=0)
    command.add_argument("--max-nfev", type=int, default=600)
    return command


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    catalogues = arguments.catalogue or sorted((PACKAGE / "data").glob("stars_*.csv"))
    return run_batch(
        arguments.solutions,
        catalogues,
        arguments.output,
        workers=arguments.workers,
        max_order=arguments.max_order,
        fold_count=arguments.fold_count,
        bootstrap_replicates=arguments.bootstrap_replicates,
        seed=arguments.seed,
        max_nfev=arguments.max_nfev,
    )


if __name__ == "__main__":
    raise SystemExit(main())
