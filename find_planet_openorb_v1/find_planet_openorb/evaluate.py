from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Sequence

import numpy as np

from .mpc3 import Mpc3Record
from .openorb_parse import EphemerisRow


@dataclass(frozen=True)
class BaselineModel:
    kind: str
    epoch_mjd_utc: float
    coefficients: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class PredictionScore:
    name: str
    count: int
    median_arcsec: float
    rms_arcsec: float
    p90_arcsec: float
    weighted_chi_square: float
    residuals_arcsec: tuple[float, ...]


@dataclass(frozen=True)
class EvaluationResult:
    status: str
    primary: PredictionScore
    alternatives: tuple[PredictionScore, ...]
    fixed_direction: PredictionScore
    angular_velocity: PredictionScore
    reason: str


def _mjd(record: Mpc3Record) -> float:
    return record.observation_time_utc.timestamp() / 86400.0 + 40587.0


def _unit(ra_deg: float, dec_deg: float) -> np.ndarray:
    ra, dec = np.radians((ra_deg, dec_deg))
    return np.array((np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)))


def _normalize(rows: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(rows, axis=1)
    if np.any(norms == 0.0):
        raise ValueError("zero baseline direction")
    return rows / norms[:, None]


def fit_fixed_direction(train: Sequence[Mpc3Record]) -> BaselineModel:
    if not train:
        raise ValueError("empty training observations")
    mean = np.mean([_unit(row.ra_deg, row.dec_deg) for row in train], axis=0)
    return BaselineModel("fixed_direction", _mjd(train[0]), (tuple(mean),))


def fit_angular_velocity(train: Sequence[Mpc3Record]) -> BaselineModel:
    if len(train) < 2:
        raise ValueError("angular-velocity baseline needs two observations")
    epoch = _mjd(train[0])
    times = np.array([_mjd(row) - epoch for row in train])
    design = np.column_stack((np.ones(len(times)), times))
    vectors = np.array([_unit(row.ra_deg, row.dec_deg) for row in train])
    coefficients = np.linalg.lstsq(design, vectors, rcond=None)[0]
    return BaselineModel("angular_velocity", epoch, tuple(tuple(row) for row in coefficients))


def predict_baseline(model: BaselineModel, rows: Sequence[Mpc3Record]) -> np.ndarray:
    if model.kind == "fixed_direction":
        return _normalize(np.tile(np.asarray(model.coefficients[0]), (len(rows), 1)))
    if model.kind == "angular_velocity":
        times = np.array([_mjd(row) - model.epoch_mjd_utc for row in rows])
        return _normalize(np.column_stack((np.ones(len(times)), times)) @ np.asarray(model.coefficients))
    raise ValueError(f"unknown baseline {model.kind}")


def score_predictions(name: str, measured: Sequence[Mpc3Record], predicted: np.ndarray) -> PredictionScore:
    if len(measured) != len(predicted) or not measured:
        raise ValueError("prediction rows must match nonempty measured rows")
    actual = np.array([_unit(row.ra_deg, row.dec_deg) for row in measured])
    predicted = _normalize(np.asarray(predicted, dtype=float))
    angles = np.degrees(np.arccos(np.clip(np.sum(actual * predicted, axis=1), -1.0, 1.0))) * 3600.0
    sigmas = np.array([math.sqrt(row.sigma_ra_arcsec * row.sigma_dec_arcsec) for row in measured])
    return PredictionScore(
        name, len(angles), float(np.median(angles)), float(np.sqrt(np.mean(angles**2))),
        float(np.quantile(angles, 0.9)), float(np.sum((angles / sigmas) ** 2)),
        tuple(float(value) for value in angles),
    )


def score_ephemeris(name: str, measured: Sequence[Mpc3Record], rows: Sequence[EphemerisRow]) -> PredictionScore:
    if len(measured) != len(rows):
        raise ValueError("ephemeris and measured row counts differ")
    for measured_row, predicted_row in zip(measured, rows, strict=True):
        if measured_row.obscode != predicted_row.observatory_code or abs(_mjd(measured_row) - predicted_row.mjd_utc) > 2e-7:
            raise ValueError("ephemeris row identity/time mismatch")
    return score_predictions(name, measured, np.array([_unit(row.ra_deg, row.dec_deg) for row in rows]))


def evaluate_openorb(
    train: Sequence[Mpc3Record], withheld: Sequence[Mpc3Record],
    primary_rows: Sequence[EphemerisRow], alternatives: Sequence[tuple[str, Sequence[EphemerisRow]]],
    family_delta_chi_square: float = 25.0,
) -> EvaluationResult:
    fixed = score_predictions("fixed_direction", withheld, predict_baseline(fit_fixed_direction(train), withheld))
    velocity = score_predictions("angular_velocity", withheld, predict_baseline(fit_angular_velocity(train), withheld))
    primary = score_ephemeris("primary_openorb", withheld, primary_rows)
    alternative_scores = tuple(score_ephemeris(name, withheld, rows) for name, rows in alternatives)
    improves = all(primary.weighted_chi_square + 25.0 <= baseline.weighted_chi_square for baseline in (fixed, velocity))
    indistinguishable = [row for row in alternative_scores if row.weighted_chi_square <= primary.weighted_chi_square + family_delta_chi_square]
    if improves and indistinguishable:
        status, reason = "multimodal", "distinct supported OpenOrb families remain within the held-out delta-chi-square gate"
    elif improves:
        status, reason = "predictive", "primary OpenOrb family improves on both matched baselines"
    else:
        status, reason = "not_predictive", "primary OpenOrb family does not improve on both matched baselines"
    return EvaluationResult(status, primary, alternative_scores, fixed, velocity, reason)


def evaluation_dict(result: EvaluationResult) -> dict[str, object]:
    return asdict(result)
