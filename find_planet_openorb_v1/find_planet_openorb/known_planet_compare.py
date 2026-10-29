from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .openorb_parse import parse_lsl


JPL_SOURCE = "https://ssd.jpl.nasa.gov/planets/approx_pos.html"
JPL_ELEMENTS_1800_2050 = {
    "Mercury": ((0.38709927, 0.20563593, 7.00497902), (0.00000037, 0.00001906, -0.00594749)),
    "Venus": ((0.72333566, 0.00677672, 3.39467605), (0.00000390, -0.00004107, -0.00078890)),
    "Earth-Moon barycenter": ((1.00000261, 0.01671123, -0.00001531), (0.00000562, -0.00004392, -0.01294668)),
    "Mars": ((1.52371034, 0.09339410, 1.84969142), (0.00001847, 0.00007882, -0.00813131)),
    "Jupiter": ((5.20288700, 0.04838624, 1.30439695), (-0.00011607, -0.00013253, -0.00183714)),
    "Saturn": ((9.53667594, 0.05386179, 2.48599187), (-0.00125060, -0.00050991, 0.00193609)),
}


def _at_epoch(name: str, mjd_tt: float) -> np.ndarray:
    base, rate = JPL_ELEMENTS_1800_2050[name]
    centuries = (mjd_tt + 2400000.5 - 2451545.0) / 36525.0
    return np.asarray(base) + centuries * np.asarray(rate)


def write_known_planet_comparison(output: Path, seal_path: Path, orbit_paths: dict[str, Path]) -> Path:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    seal = json.loads(Path(seal_path).read_text())
    records = {}
    for label, path in orbit_paths.items():
        orbit = parse_lsl(path)[0]
        planets = {}
        for name in JPL_ELEMENTS_1800_2050:
            known = _at_epoch(name, orbit.epoch_mjd_tt)
            delta_sigma = (np.asarray(orbit.elements[:3]) - known) / np.asarray(orbit.standard_deviations[:3])
            planets[name] = {"jpl_a_e_i": known.tolist(), "delta_sigma_a_e_i": delta_sigma.tolist(),
                             "quadrature_sigma_a_e_i": float(np.linalg.norm(delta_sigma))}
        records[label] = {"orbit_path": str(Path(path).resolve()), "fitted_a_e_i": orbit.elements[:3],
                          "sigma_a_e_i": orbit.standard_deviations[:3], "planet_comparisons": planets,
                          "nearest_by_a_e_i_sigma": min(planets, key=lambda name: planets[name]["quadrature_sigma_a_e_i"])}
    payload = {"anonymous_seal_sha256": seal["seal_sha256"], "jpl_source": JPL_SOURCE,
               "comparison_is_post_seal": True, "families": records}
    (output / "known-planet-comparison.json").write_text(json.dumps(payload, indent=2) + "\n")

    fig, ax = plt.subplots(figsize=(9, 6))
    epoch = parse_lsl(next(iter(orbit_paths.values())))[0].epoch_mjd_tt
    for name in JPL_ELEMENTS_1800_2050:
        a, e, _ = _at_epoch(name, epoch)
        ax.scatter(a, e, marker="*", s=110, label=name)
        ax.annotate(name, (a, e), xytext=(4, 5), textcoords="offset points", fontsize=8)
    colors = ("black", "tab:orange", "tab:blue", "tab:green")
    for color, (label, path) in zip(colors, orbit_paths.items()):
        orbit = parse_lsl(path)[0]
        ax.errorbar(orbit.elements[0], orbit.elements[1], xerr=orbit.standard_deviations[0],
                    yerr=orbit.standard_deviations[1], fmt="o", capsize=3, color=color, label=f"Object A: {label}")
    ax.set(xlabel="semimajor axis a (au)", ylabel="eccentricity e",
           title="Post-seal comparison with JPL approximate planetary elements", xlim=(0.2, 3.4), ylim=(-0.02, 0.48))
    ax.grid(alpha=0.25); ax.legend(fontsize=8, ncol=2); fig.tight_layout()
    fig.savefig(output / "known-planet-elements.png", dpi=180); plt.close(fig)
    return output
