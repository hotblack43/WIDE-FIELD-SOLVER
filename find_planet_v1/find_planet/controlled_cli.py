"""Controlled Object A extraction, orbit fitting, reporting, and sealing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Sequence

from .barghini import anonymous_direction_rows
from .evaluate import evaluate_controlled
from .extract_controlled import (
    load_exact_receipts,
    select_answer_key_rows,
    write_answer_key_audit,
)
from .fitting import FitConfig
from .observer import build_observations
from .provenance import new_output_directory, sha256_file
from .report import write_controlled_report
from .seal import seal_output, verify_seal


DEFAULT_AUDIT = Path("results/photometry-runs/v23-20261027T050447Z/planet-empirical-extinction/B/planet_only_airmass_correction_audit.csv")
DEFAULT_AUDIT_SHA256 = "e0f445e044382369aa4a468a53900b1192cd7859389b9c388dd00c8633be6924"
DEFAULT_DATABASE = Path("results/stars.sqlite")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fit Object A without supplying its identity to the orbit solver")
    parser.add_argument("--results-root", type=Path, default=Path("results/find-planet-v1"))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--audit-sha256", default=DEFAULT_AUDIT_SHA256)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--maximum-seeds", type=int, default=24)
    parser.add_argument("--max-nfev", type=int, default=300)
    parser.add_argument("--bootstrap-replicates", type=int, default=100)
    parser.add_argument("--bootstrap-seed", type=int, default=1729)
    return parser


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not arguments.audit.is_file() or not arguments.database.is_file():
        print("controlled inputs are missing: audit and database must both exist", file=sys.stderr)
        return 2
    if arguments.maximum_seeds <= 0 or arguments.max_nfev <= 0 or arguments.bootstrap_replicates < 0:
        print("fit limits must be positive and bootstrap replicates nonnegative", file=sys.stderr)
        return 2
    run_id = arguments.run_id or _run_id()
    try:
        output = new_output_directory(arguments.results_root, run_id)
    except (FileExistsError, OSError) as error:
        print(f"cannot create fresh output: {error}", file=sys.stderr)
        return 2
    try:
        selected, answer_key_rows = select_answer_key_rows(
            arguments.audit, arguments.audit_sha256, object_name="Mars"
        )
        receipts = load_exact_receipts(arguments.database, selected)
        directions = anonymous_direction_rows(selected, receipts)
        observations = build_observations(directions)
        evaluation = evaluate_controlled(
            observations,
            FitConfig(max_nfev=arguments.max_nfev, maximum_seed_count=arguments.maximum_seeds),
            bootstrap_replicates=arguments.bootstrap_replicates,
            bootstrap_seed=arguments.bootstrap_seed,
        )
        answer_key_path = output / "answer_key_selection.csv"
        write_answer_key_audit(answer_key_path, answer_key_rows)
        products = [answer_key_path]
        products.extend(write_controlled_report(
            output,
            {"observations": tuple(observations), "audit_rows": tuple(answer_key_rows)},
            evaluation.primary_fit,
            evaluation,
        ))
        runtime_root = Path(__file__).resolve().parents[1]
        source_manifest = runtime_root / "source-manifest.json"
        inputs = {
            "audit_sha256": sha256_file(arguments.audit),
            "database_sha256": sha256_file(arguments.database),
            "dependency_lock_sha256": sha256_file(runtime_root / "uv.lock"),
            "source_manifest_sha256": sha256_file(source_manifest) if source_manifest.is_file() else "pending-task-9",
            "exact_run_ids": json.dumps([row.run_id for row in selected], separators=(",", ":")),
            "command_arguments": json.dumps(list(argv) if argv is not None else sys.argv[1:], separators=(",", ":")),
            "coordinate_convention": "measured vacuum ICRS unit vectors; heliocentric ICRS Cartesian states",
            "time_convention": "verified exposure midpoint UTC converted to TDB Julian date",
            "scientific_status": evaluation.scientific_status,
        }
        seal = seal_output(output, products, inputs)
        verification = verify_seal(seal)
        if not verification.valid:
            raise RuntimeError("newly written seal failed verification: " + "; ".join(verification.errors))
        print(output)
        return 0
    except Exception as error:
        error_path = output / "operational_error.json"
        try:
            error_path.write_text(json.dumps({"status": "operational_error", "error": str(error)}, indent=2) + "\n")
        except OSError:
            pass
        print(f"controlled run failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
