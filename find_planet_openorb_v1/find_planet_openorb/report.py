from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .evaluate import evaluate_openorb, evaluation_dict
from .mpc3 import parse_mpc3_records
from .openorb_parse import covariance_support, parse_ephemeris, parse_lsl


def write_anonymous_report(
    output: Path, fit_path: Path, withheld_path: Path,
    primary_orbit_path: Path, primary_ephemeris_path: Path,
    alternative_orbit_path: Path, alternative_ephemeris_path: Path,
) -> Path:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    fit = parse_mpc3_records(fit_path)
    withheld = parse_mpc3_records(withheld_path)
    primary_eph = parse_ephemeris(primary_ephemeris_path)
    alternative_eph = parse_ephemeris(alternative_ephemeris_path)
    result = evaluate_openorb(fit, withheld, primary_eph, (("alternative_openorb", alternative_eph),))
    primary_orbit = parse_lsl(primary_orbit_path)[0]
    alternative_orbit = parse_lsl(alternative_orbit_path)[0]
    payload = evaluation_dict(result)
    payload["primary_orbit"] = {
        "element_type": primary_orbit.element_type, "epoch_mjd_tt": primary_orbit.epoch_mjd_tt,
        "elements": primary_orbit.elements, "standard_deviations": primary_orbit.standard_deviations,
        "covariance_support": covariance_support(primary_orbit.covariance).__dict__,
    }
    payload["alternative_orbit"] = {
        "element_type": alternative_orbit.element_type, "epoch_mjd_tt": alternative_orbit.epoch_mjd_tt,
        "elements": alternative_orbit.elements, "standard_deviations": alternative_orbit.standard_deviations,
        "covariance_support": covariance_support(alternative_orbit.covariance).__dict__,
    }
    (output / "anonymous-evaluation.json").write_text(json.dumps(payload, indent=2) + "\n")

    with (output / "withheld-scores.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("model", "count", "median_arcsec", "p90_arcsec", "rms_arcsec", "weighted_chi_square"))
        for score in (result.primary, *result.alternatives, result.angular_velocity, result.fixed_direction):
            writer.writerow((score.name, score.count, score.median_arcsec, score.p90_arcsec, score.rms_arcsec, score.weighted_chi_square))

    fig, ax = plt.subplots(figsize=(9, 6))
    ax.scatter([row.ra_deg for row in fit], [row.dec_deg for row in fit], s=11, color="0.65", label="fit measurements")
    ax.scatter([row.ra_deg for row in withheld], [row.dec_deg for row in withheld], s=24, facecolors="none", edgecolors="black", label="withheld measurements")
    ax.plot([row.ra_deg for row in primary_eph], [row.dec_deg for row in primary_eph], ".", ms=5, label="primary OpenOrb prediction")
    ax.plot([row.ra_deg for row in alternative_eph], [row.dec_deg for row in alternative_eph], ".", ms=4, label="alternative OpenOrb prediction")
    ax.set(xlabel="ICRS right ascension (deg)", ylabel="ICRS declination (deg)", title="Anonymous Object A: measured track and withheld predictions")
    ax.invert_xaxis(); ax.grid(alpha=0.25); ax.legend()
    fig.tight_layout(); fig.savefig(output / "anonymous-sky-track.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    for score in (result.primary, *result.alternatives, result.angular_velocity):
        values = np.sort(score.residuals_arcsec)
        ax.step(values, np.arange(1, len(values) + 1) / len(values), where="post", label=score.name)
    ax.set(xscale="log", xlabel="withheld angular residual (arcsec, log scale)", ylabel="cumulative fraction", title="Held-out predictive residuals")
    ax.grid(alpha=0.25, which="both"); ax.legend(); fig.tight_layout()
    fig.savefig(output / "withheld-residual-cdf.png", dpi=180); plt.close(fig)
    return output
