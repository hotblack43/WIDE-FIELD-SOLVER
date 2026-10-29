from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from typing import Mapping

from .provenance import OpenOrbInstallation


PERTURBER_NAMES = (
    "Mercury", "Venus", "Earth", "Moon", "Mars", "Jupiter", "Saturn",
    "Uranus", "Neptune", "Pluto", "asteroids",
)


@dataclass(frozen=True)
class RangingBudget:
    accepted_samples: int
    maximum_trials: int
    iterations: int
    timeout_seconds: float


@dataclass(frozen=True)
class ConfigAudit:
    path: Path
    dynamical_model: str
    ephemeris_name: str
    perturbers: Mapping[str, bool]
    budget: RangingBudget


@dataclass(frozen=True)
class OpenOrbRunSpec:
    task: str
    input_path: Path
    config_path: Path
    product_path: Path
    budget: RangingBudget | None = None
    orbit_input_path: Path | None = None


@dataclass(frozen=True)
class OpenOrbRunReceipt:
    status: str
    task: str
    command: tuple[str, ...]
    returncode: int | None
    elapsed_seconds: float
    accepted_samples: int | None
    terminated: bool
    stdout_path: Path
    stderr_path: Path
    product_path: Path


def _read_config(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"malformed OpenOrb configuration line: {raw_line}")
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def materialize_config(base: Path, overlay: Path, destination: Path) -> Path:
    """Write a complete OpenOrb configuration with an audited local overlay.

    The stock OpenOrb configuration fixes RA/Dec errors at one arcsecond.  That
    would silently override the per-observation MPC3 errors, so those two keys
    are deliberately omitted unless the overlay explicitly supplies them.
    """
    replacements = _read_config(overlay)
    lines: list[str] = []
    replaced: set[str] = set()
    for raw_line in Path(base).read_text(encoding="utf-8").splitlines():
        content = raw_line.split("#", 1)[0].strip()
        key = content.split(":", 1)[0].strip() if ":" in content else None
        if key in {"stdev.ra", "stdev.dec"} and key not in replacements:
            lines.append(f"# {raw_line}  # disabled: use MPC3 per-observation uncertainty")
        elif key in replacements:
            lines.append(f"{key}: {replacements[key]}")
            replaced.add(key)
        else:
            lines.append(raw_line)
    for key, value in replacements.items():
        if key not in replaced:
            lines.append(f"{key}: {value}")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return destination


def audit_config(path: Path, expected_budget: RangingBudget) -> ConfigAudit:
    values = _read_config(path)
    if values.get("dynamical_model") != "2-body" or values.get("dynamical_model_init") != "2-body":
        raise ValueError("anonymous target configuration must use two-body dynamics")
    perturbers = {name: values.get(f"perturber.{name}") == "T" for name in PERTURBER_NAMES}
    if any(perturbers.values()) or any(f"perturber.{name}" not in values for name in PERTURBER_NAMES):
        raise ValueError("every target perturber must be explicitly disabled")
    actual = RangingBudget(
        int(values["sor.norb"]), int(values["sor.ntrial"]), int(values["sor.niter"]),
        expected_budget.timeout_seconds,
    )
    if actual != expected_budget or values.get("sor.type") != "2":
        raise ValueError(f"OpenOrb ranging budget mismatch: {actual!r}")
    if values.get("relativity") != "F":
        raise ValueError("two-body anonymous target configuration must disable relativity")
    return ConfigAudit(Path(path), "2-body", values.get("planetary_ephemeris_fname", ""), perturbers, actual)


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _accepted_samples(text: str, product_path: Path | None = None) -> int | None:
    matches = re.findall(r"Accepted sample orbits:\s*(\d+)", text, flags=re.IGNORECASE)
    if matches:
        return int(matches[-1])
    if product_path is not None and product_path.is_file():
        rows = [line for line in product_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
        return len(rows)
    return None


def run_openorb(
    spec: OpenOrbRunSpec,
    installation: OpenOrbInstallation,
    output: Path,
) -> OpenOrbRunReceipt:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for required in (spec.input_path, spec.config_path):
        if not Path(required).is_file():
            raise FileNotFoundError(required)
    command = [
        str(installation.executable), f"--task={spec.task}",
        f"--obs-in={Path(spec.input_path).resolve()}",
        f"--conf={Path(spec.config_path).resolve()}",
    ]
    if spec.task != "ephemeris":
        command.append(f"--orb-out={Path(spec.product_path).resolve()}")
    command.append("--fixran")
    if spec.orbit_input_path is not None:
        command.insert(-1, f"--orb-in={Path(spec.orbit_input_path).resolve()}")
    environment = {
        "PATH": "/usr/bin:/bin", "OORB_DATA": str(installation.data_directory),
        "LC_ALL": "C", "LANG": "C", "HOME": str(output.resolve()),
    }
    stdout_path, stderr_path = output / "stdout.log", output / "stderr.log"
    start = time.monotonic()
    terminated = False
    returncode: int | None = None
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            command, cwd=output, env=environment, stdout=stdout, stderr=stderr,
            text=True, start_new_session=True,
        )
        try:
            returncode = process.wait(timeout=spec.budget.timeout_seconds if spec.budget else None)
        except subprocess.TimeoutExpired:
            terminated = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                returncode = process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                returncode = process.wait()
    elapsed = time.monotonic() - start
    stdout_text = stdout_path.read_text(encoding="utf-8")
    stderr_text = stderr_path.read_text(encoding="utf-8")
    if spec.task == "ephemeris" and returncode == 0 and "***ERROR***" not in stderr_text:
        temporary = Path(spec.product_path).with_name(f".{Path(spec.product_path).name}.tmp")
        temporary.write_text(stdout_text, encoding="utf-8")
        temporary.replace(spec.product_path)
    accepted = _accepted_samples(stdout_text, spec.product_path if spec.task == "ranging" else None)
    if terminated:
        status = "timed_out"
    elif returncode != 0 or "***ERROR***" in stderr_text:
        status = "execution_failed"
    elif spec.task == "ranging" and (spec.budget is None or accepted is None or accepted < spec.budget.accepted_samples):
        status = "search_incomplete"
    elif not spec.product_path.is_file():
        status = "execution_failed"
    else:
        status = "success"
    receipt = OpenOrbRunReceipt(
        status, spec.task, tuple(command), returncode, elapsed, accepted, terminated,
        stdout_path, stderr_path, spec.product_path,
    )
    payload = asdict(receipt)
    for key, value in tuple(payload.items()):
        if isinstance(value, Path): payload[key] = str(value)
        elif isinstance(value, tuple): payload[key] = list(value)
    payload["environment"] = environment
    _atomic_json(output / "openorb-run-receipt.json", payload)
    return receipt


def run_ranging(spec: OpenOrbRunSpec, installation: OpenOrbInstallation, output: Path) -> OpenOrbRunReceipt:
    if spec.task != "ranging": raise ValueError("ranging wrapper requires task='ranging'")
    return run_openorb(spec, installation, output)


def run_lsl(spec: OpenOrbRunSpec, installation: OpenOrbInstallation, output: Path) -> OpenOrbRunReceipt:
    if spec.task != "lsl": raise ValueError("LSL wrapper requires task='lsl'")
    return run_openorb(spec, installation, output)


def run_ephemeris(spec: OpenOrbRunSpec, installation: OpenOrbInstallation, output: Path) -> OpenOrbRunReceipt:
    if spec.task != "ephemeris": raise ValueError("ephemeris wrapper requires task='ephemeris'")
    return run_openorb(spec, installation, output)
