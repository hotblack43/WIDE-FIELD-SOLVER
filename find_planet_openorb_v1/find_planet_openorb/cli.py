from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import json
from pathlib import Path

from .barghini import anonymous_direction_rows
from .extract_controlled import load_exact_receipts, select_answer_key_rows, write_answer_key_audit
from .known_planet_compare import write_known_planet_comparison
from .mpc3 import validate_mpc3_with_openorb, write_mpc3
from .observations import directions_to_observations, split_nights
from .openorb_runtime import (
    OpenOrbRunSpec, RangingBudget, materialize_config, run_ephemeris, run_lsl,
    run_ranging,
)
from .provenance import new_output_directory, verify_installation
from .report import write_anonymous_report
from .seal import write_anonymous_seal


def _write_anonymous_csv(path: Path, rows, partition: str) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("anonymous_object_id", "run_id", "source_sha256", "night", "observation_time_utc",
                         "ra_deg", "dec_deg", "sigma_ra_arcsec", "sigma_dec_arcsec", "partition"))
        for row in rows:
            writer.writerow((row.object_id, row.run_id, row.source_sha256, row.night,
                             row.observation_time_utc.isoformat().replace("+00:00", "Z"), row.ra_deg,
                             row.dec_deg, row.sigma_ra_arcsec, row.sigma_dec_arcsec, partition))


def _seed_from_mpc3(source: Path, destination: Path, indices: tuple[int, int, int]) -> None:
    lines = source.read_text().splitlines()
    count = len(lines) // 2
    if any(index < 0 or index >= count for index in indices):
        raise ValueError("seed observation index outside input")
    destination.write_text("\n".join(value for index in indices for value in lines[2 * index:2 * index + 2]) + "\n")


def _run_family(name: str, indices: tuple[int, int, int], run: Path, fit: Path, withheld: Path,
                project: Path, installation):
    family = run / name
    ranging_dir = family / "ranging"; ranging_dir.mkdir(parents=True)
    seed = ranging_dir / "seed.mpc3"; _seed_from_mpc3(fit, seed, indices)
    config = materialize_config(installation.configuration, project / "config/primary.conf", ranging_dir / "primary.conf")
    budget = RangingBudget(5000, 5_000_000, 3, 3600.0)
    ranging = run_ranging(OpenOrbRunSpec("ranging", seed, config, ranging_dir / "samples.orb", budget), installation, ranging_dir)
    if ranging.status != "success":
        raise RuntimeError(f"{name} ranging did not complete: {ranging.status}")
    lsl_dir = family / "lsl"; lsl_dir.mkdir()
    lsl_config = materialize_config(installation.configuration, project / "config/primary.conf", lsl_dir / "lsl.conf")
    lsl_config.write_text(lsl_config.read_text().replace("element_type_out: cartesian", "element_type_out: keplerian"))
    lsl = run_lsl(OpenOrbRunSpec("lsl", fit, lsl_config, lsl_dir / "solution.orb", None, ranging_dir / "samples.orb"), installation, lsl_dir)
    if lsl.status != "success":
        raise RuntimeError(f"{name} LSL did not complete: {lsl.status}")
    eph_dir = family / "withheld-ephemeris"; eph_dir.mkdir()
    eph = run_ephemeris(OpenOrbRunSpec("ephemeris", withheld, lsl_config, eph_dir / "withheld.eph", None,
                                      lsl_dir / "solution.orb"), installation, eph_dir)
    if eph.status != "success":
        raise RuntimeError(f"{name} ephemeris did not complete: {eph.status}")
    return ranging_dir / "samples.orb", lsl_dir / "solution.orb", eph_dir / "withheld.eph", config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Identity-neutral native OpenOrb planet experiment")
    parser.add_argument("--vendor-root", type=Path, required=True)
    parser.add_argument("--sources-manifest", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--reveal-known-planets", action="store_true")
    return parser


def _evidence_repository(project: Path) -> Path:
    checkout = project.parent
    marker = checkout / ".git"
    if marker.is_file():
        value = marker.read_text().strip()
        if value.startswith("gitdir: "):
            git_directory = Path(value.removeprefix("gitdir: ")).resolve()
            if git_directory.parent.name == "worktrees":
                return git_directory.parents[2]
    return checkout


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project = Path(__file__).resolve().parents[1]
    evidence_repo = _evidence_repository(project)
    audit = args.audit or evidence_repo / "results/photometry-runs/v23-20261027T050447Z/planet-empirical-extinction/B/planet_only_airmass_correction_audit.csv"
    database = args.database or evidence_repo / "results/stars.sqlite"
    run_id = args.run_id or datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    run = new_output_directory(args.results_root, run_id)
    installation = verify_installation(args.vendor_root, args.sources_manifest)

    selected, answer_audit = select_answer_key_rows(audit)
    write_answer_key_audit(run / "answer-key-selection.csv", answer_audit)
    receipts = load_exact_receipts(database, selected)
    observations = directions_to_observations(anonymous_direction_rows(selected, receipts))
    split = split_nights(observations)
    inputs = run / "anonymous-inputs"; inputs.mkdir()
    fit, withheld = inputs / "fit.mpc3", inputs / "withheld.mpc3"
    write_mpc3(fit, split.fit, "OBJ000001"); write_mpc3(withheld, split.withheld, "OBJ000001")
    _write_anonymous_csv(inputs / "fit.csv", split.fit, "fit")
    _write_anonymous_csv(inputs / "withheld.csv", split.withheld, "withheld")
    validate_mpc3_with_openorb(installation, fit); validate_mpc3_with_openorb(installation, withheld)
    (inputs / "split.json").write_text(json.dumps({"fit_nights": split.fit_nights,
        "withheld_nights": split.withheld_nights, "fit_count": len(split.fit),
        "withheld_count": len(split.withheld), "rule": "every fifth chronological usable night"}, indent=2) + "\n")

    n = len(split.fit)
    primary = _run_family("primary", (0, n // 4, n - 1), run, fit, withheld, project, installation)
    alternative = _run_family("alternative", (0, n // 2, n - 1), run, fit, withheld, project, installation)
    report = write_anonymous_report(run / "anonymous-report", fit, withheld, primary[1], primary[2], alternative[1], alternative[2])
    seal_files = [fit, withheld, inputs / "fit.csv", inputs / "withheld.csv", inputs / "split.json",
                  primary[0], primary[1], primary[2], primary[3], alternative[0], alternative[1],
                  alternative[2], alternative[3], report / "anonymous-evaluation.json",
                  report / "withheld-scores.csv", report / "anonymous-sky-track.png", report / "withheld-residual-cdf.png"]
    status = json.loads((report / "anonymous-evaluation.json").read_text())["status"]
    write_anonymous_seal(report / "anonymous-seal.json", seal_files, status)
    if args.reveal_known_planets:
        write_known_planet_comparison(run / "known-planet-comparison", report / "anonymous-seal.json",
                                      {"sealed-primary": primary[1], "sealed-alternative": alternative[1]})
    print(json.dumps({"run": str(run), "anonymous_status": status,
                      "seal": json.loads((report / "anonymous-seal.json").read_text())["seal_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
