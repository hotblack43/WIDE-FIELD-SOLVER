from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class RangingSample:
    designation: str
    elements: tuple[float, ...]
    element_type: str
    epoch_mjd_tt: float
    inverse_pdf: float
    reduced_chi2: float
    source_sha256: str
    line_number: int


@dataclass(frozen=True)
class NominalOrbit:
    designation: str
    elements: tuple[float, ...]
    element_type: str
    epoch_mjd_tt: float
    standard_deviations: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]
    absolute_magnitude: float
    slope_parameter: float
    source_sha256: str
    line_number: int


@dataclass(frozen=True)
class CovarianceResult:
    supported: bool
    eigenvalues: tuple[float, ...]
    condition_number: float
    reason: str


@dataclass(frozen=True)
class ResidualRow:
    designation: str
    date_yyyymmdd: str
    observatory_code: str
    ra_residual_arcsec: float
    dec_residual_arcsec: float
    source_sha256: str
    line_number: int


@dataclass(frozen=True)
class EphemerisRow:
    designation: str
    observatory_code: str
    mjd_utc: float
    delta_au: float
    ra_deg: float
    dec_deg: float
    delta_uncertainty_au: float
    ra_uncertainty_deg: float
    dec_uncertainty_deg: float
    source_sha256: str
    line_number: int


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _finite(values: Sequence[float], context: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or not all(math.isfinite(value) for value in result):
        raise ValueError(f"non-finite or absent numeric data in {context}")
    return result


def _element_type(header: str) -> str:
    if "Ecliptic x" in header:
        return "cartesian"
    if "Semimajor axis a" in header:
        return "keplerian"
    raise ValueError("unrecognized OpenOrb orbit header")


def parse_ranging(path: Path) -> tuple[RangingSample, ...]:
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 5 or "Unnormalized" not in lines[0]:
        raise ValueError("not a supported OpenOrb ranging-orbit product")
    element_type = _element_type(lines[0])
    digest = _sha(path)
    output: list[RangingSample] = []
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 15 or fields[8] != element_type:
            raise ValueError(f"truncated or changed ranging row at line {number}")
        numeric = _finite([*fields[1:8], *fields[9:]], f"ranging line {number}")
        output.append(RangingSample(
            fields[0], numeric[:6], element_type, numeric[6], numeric[7], numeric[8], digest, number,
        ))
    if not output:
        raise ValueError("ranging product contains no samples")
    return tuple(output)


def parse_lsl(path: Path) -> tuple[NominalOrbit, ...]:
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) < 5 or "sigma e1" not in lines[0] or "cov(5,6)" not in lines[0]:
        raise ValueError("not a supported OpenOrb LSL orbit product")
    element_type = _element_type(lines[0])
    digest = _sha(path)
    output: list[NominalOrbit] = []
    pairs = [(i, j) for i in range(6) for j in range(i + 1, 6)]
    for number, line in enumerate(lines, 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 31:
            raise ValueError(f"truncated or changed LSL row at line {number}")
        values = _finite(fields[1:], f"LSL line {number}")
        elements, epoch = values[:6], values[6]
        stdev = values[7:13]
        covariance = np.diag(np.square(stdev))
        for value, (i, j) in zip(values[13:28], pairs, strict=True):
            covariance[i, j] = covariance[j, i] = value
        output.append(NominalOrbit(
            fields[0], elements, element_type, epoch, stdev,
            tuple(tuple(float(value) for value in row) for row in covariance),
            values[28], values[29], digest, number,
        ))
    if not output:
        raise ValueError("LSL product contains no nominal orbit")
    return tuple(output)


def covariance_support(covariance: Sequence[Sequence[float]], max_condition: float = 1.0e12) -> CovarianceResult:
    matrix = np.asarray(covariance, dtype=float)
    if matrix.shape != (6, 6) or not np.all(np.isfinite(matrix)):
        return CovarianceResult(False, (), math.inf, "missing_or_nonfinite")
    if not np.allclose(matrix, matrix.T, rtol=1e-10, atol=1e-15):
        return CovarianceResult(False, (), math.inf, "not_symmetric")
    eigenvalues = np.linalg.eigvalsh(matrix)
    values = tuple(float(value) for value in eigenvalues)
    if eigenvalues[0] <= 0.0:
        return CovarianceResult(False, values, math.inf, "not_positive_definite")
    condition = float(eigenvalues[-1] / eigenvalues[0])
    if not math.isfinite(condition) or condition > max_condition:
        return CovarianceResult(False, values, condition, "ill_conditioned")
    return CovarianceResult(True, values, condition, "supported")


def parse_residuals(path: Path) -> tuple[ResidualRow, ...]:
    path = Path(path)
    digest = _sha(path)
    output: list[ResidualRow] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("#RES"):
            continue
        fields = line.replace("(", " ").replace(")", " ").split()
        if len(fields) < 6 or (len(fields) - 2) % 4:
            raise ValueError(f"changed residual row at line {number}")
        designation = fields[1]
        for offset in range(2, len(fields), 4):
            date, code, ra_text, dec_text = fields[offset:offset + 4]
            if not re.fullmatch(r"\d{8}", date) or "*" in ra_text + dec_text:
                raise ValueError(f"invalid or overflowed residual at line {number}")
            ra, dec = _finite((ra_text, dec_text), f"residual line {number}")
            output.append(ResidualRow(designation, date, code, ra, dec, digest, number))
    if not output:
        raise ValueError("residual product contains no numeric residuals")
    return tuple(output)


def parse_ephemeris(path: Path) -> tuple[EphemerisRow, ...]:
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    required = "#Designation       Observatory_code             MJD_UTC"
    if not lines or not lines[0].startswith(required) or "CurrentEphUnc" not in lines[0]:
        raise ValueError("not a supported OpenOrb ephemeris product")
    digest = _sha(path)
    output: list[EphemerisRow] = []
    for number, line in enumerate(lines[1:], 2):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 31:
            raise ValueError(f"truncated or changed ephemeris row at line {number}")
        values = _finite(fields[2:], f"ephemeris line {number}")
        output.append(EphemerisRow(
            fields[0], fields[1], values[0], values[1], values[2] % 360.0, values[3],
            values[7], values[8], values[9], digest, number,
        ))
    if not output:
        raise ValueError("ephemeris product contains no rows")
    return tuple(output)
