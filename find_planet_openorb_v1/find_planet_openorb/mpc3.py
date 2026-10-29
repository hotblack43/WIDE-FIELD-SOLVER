from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import math
import os
from pathlib import Path
import subprocess
from typing import Sequence

from .observations import AnonymousObservation
from .provenance import OpenOrbInstallation


@dataclass(frozen=True)
class Mpc3Record:
    designation: str
    observation_time_utc: datetime
    ra_deg: float
    dec_deg: float
    sigma_ra_arcsec: float
    sigma_dec_arcsec: float
    correlation: float
    obscode: str


@dataclass(frozen=True)
class Mpc3Validation:
    accepted_records: int
    command: tuple[str, ...]
    converted_path: Path
    stdout: str
    stderr: str


def _put(record: list[str], first: int, last: int, value: str) -> None:
    width = last - first + 1
    if len(value) != width:
        raise ValueError(f"field {first}:{last} needs {width} characters, got {value!r}")
    record[first - 1:last] = value


def _sexagesimal_ra(ra_deg: float) -> tuple[int, int, float]:
    total_seconds = (ra_deg % 360.0) * 240.0
    hours = int(total_seconds // 3600)
    minutes = int(total_seconds % 3600 // 60)
    seconds = total_seconds - 3600 * hours - 60 * minutes
    if seconds >= 59.99995:
        seconds = 0.0
        minutes += 1
        if minutes == 60:
            minutes = 0
            hours = (hours + 1) % 24
    return hours, minutes, seconds


def _sexagesimal_dec(dec_deg: float) -> tuple[str, int, int, float]:
    sign = "-" if math.copysign(1.0, dec_deg) < 0 else "+"
    absolute = abs(dec_deg)
    degrees = int(absolute)
    minutes = int((absolute - degrees) * 60)
    seconds = (absolute * 3600) - degrees * 3600 - minutes * 60
    if seconds >= 59.9995:
        seconds = 0.0
        minutes += 1
        if minutes == 60:
            minutes = 0
            degrees += 1
    return sign, degrees, minutes, seconds


def _designation_field(designation: str) -> str:
    if not designation or len(designation) > 9 or not designation.isascii() or any(character.isspace() for character in designation):
        raise ValueError("neutral MPC3 designation must be one to nine non-space ASCII characters")
    return designation.ljust(9)


def _obscode_field(obscode: str) -> str:
    if len(obscode) == 3:
        obscode = "0" + obscode
    if len(obscode) != 4 or not obscode.isalnum():
        raise ValueError("MPC3 observatory code must contain three or four alphanumeric characters")
    return obscode


def _record_pair(observation: AnonymousObservation, designation: str, obscode: str) -> tuple[str, str]:
    first = [" "] * 132
    second = [" "] * 132
    designation_field = _designation_field(designation)
    _put(first, 8, 16, designation_field)
    _put(second, 8, 16, designation_field)
    _put(first, 19, 19, "1")
    _put(second, 19, 20, "2+")
    epoch = observation.observation_time_utc.astimezone(UTC)
    midnight = datetime(epoch.year, epoch.month, epoch.day, tzinfo=UTC)
    fractional_day = (epoch - midnight).total_seconds() / 86400.0
    _put(first, 22, 25, f"{epoch.year:04d}")
    _put(first, 26, 27, f"{epoch.month:02d}")
    _put(first, 28, 39, f"{epoch.day + fractional_day:012.9f}")
    hours, minutes, seconds = _sexagesimal_ra(observation.ra_deg)
    _put(first, 41, 42, f"{hours:02d}")
    _put(first, 44, 45, f"{minutes:02d}")
    _put(first, 47, 53, f"{seconds:07.4f}")
    sign, degrees, arcminutes, arcseconds = _sexagesimal_dec(observation.dec_deg)
    _put(first, 56, 56, sign)
    _put(first, 57, 58, f"{degrees:02d}")
    _put(first, 60, 61, f"{arcminutes:02d}")
    _put(first, 63, 68, f"{arcseconds:06.3f}")
    for sigma, first_column in ((observation.sigma_ra_arcsec, 41), (observation.sigma_dec_arcsec, 48)):
        if not 0 < sigma < 1000.0:
            raise ValueError("MPC3 angular uncertainty must be below 1000 arcsec")
        encoded = f"{sigma:06.3f}" if sigma < 100.0 else f"{sigma / 10.0:04.1f}E1"
        _put(second, first_column, first_column + 5, encoded)
    _put(second, 57, 64, f"{0.0:8.5f}")
    code = _obscode_field(obscode)
    _put(first, 129, 132, code)
    _put(second, 129, 132, code)
    return "".join(first), "".join(second)


def write_mpc3(
    path: Path,
    observations: Sequence[AnonymousObservation],
    designation: str,
    obscode: str = "696",
) -> None:
    if not observations:
        raise ValueError("at least one anonymous observation is required")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="ascii", newline="\n") as handle:
        for observation in observations:
            first, second = _record_pair(observation, designation, obscode)
            handle.write(first + "\n" + second + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def parse_mpc3_records(path: Path) -> tuple[Mpc3Record, ...]:
    lines = Path(path).read_text(encoding="ascii").splitlines()
    if len(lines) % 2:
        raise ValueError("MPC3 input ended between record lines")
    output: list[Mpc3Record] = []
    for offset in range(0, len(lines), 2):
        first, second = lines[offset:offset + 2]
        if len(first) != 132 or len(second) != 132 or first[18] != "1" or second[18:20] != "2+":
            raise ValueError("invalid two-record MPC3 layout")
        year, month, day_value = int(first[21:25]), int(first[25:27]), float(first[27:39])
        day = int(day_value)
        epoch = datetime(year, month, day, tzinfo=UTC) + timedelta(days=day_value - day)
        hours, minutes, seconds = int(first[40:42]), int(first[43:45]), float(first[46:53])
        ra_deg = 15.0 * (hours + minutes / 60.0 + seconds / 3600.0)
        sign = -1.0 if first[55] == "-" else 1.0
        degrees, arcminutes, arcseconds = int(first[56:58]), int(first[59:61]), float(first[62:68])
        dec_deg = sign * (degrees + arcminutes / 60.0 + arcseconds / 3600.0)
        code = first[128:132]
        if second[42] == ".":
            sigma_ra = float(second[40:46])
            sigma_dec = float(second[47:53])
        else:
            radians_to_arcsec = 180.0 * 3600.0 / math.pi
            sigma_ra = float(second[40] + "." + second[41:48]) * 1.0e-7 * radians_to_arcsec
            sigma_dec = float(second[48] + "." + second[49:56]) * 1.0e-7 * radians_to_arcsec
        output.append(Mpc3Record(
            designation=first[7:16].strip(), observation_time_utc=epoch,
            ra_deg=ra_deg, dec_deg=dec_deg,
            sigma_ra_arcsec=sigma_ra, sigma_dec_arcsec=sigma_dec,
            correlation=float(second[56:64]), obscode=code[1:] if code.startswith("0") else code,
        ))
    return tuple(output)


def validate_mpc3_with_openorb(
    installation: OpenOrbInstallation | None, path: Path,
) -> Mpc3Validation:
    if installation is None:
        raise FileNotFoundError("a verified OpenOrb installation is required for native MPC3 validation")
    records = parse_mpc3_records(path)
    converted = Path(path).with_suffix(".native.mpc")
    command = (
        str(installation.executable), "--task=tompc", f"--obs-in={Path(path).resolve()}",
        f"--obs-out={converted.resolve()}", f"--conf={installation.configuration}", "--fixran",
    )
    environment = {"PATH": "/usr/bin:/bin", "OORB_DATA": str(installation.data_directory), "LC_ALL": "C"}
    result = subprocess.run(command, cwd=Path(path).parent, env=environment, text=True, capture_output=True, check=False)
    if result.returncode != 0 or not converted.is_file():
        raise RuntimeError(f"native OpenOrb MPC3 validation failed ({result.returncode}): {result.stderr.strip()}")
    return Mpc3Validation(len(records), command, converted, result.stdout, result.stderr)
