"""Fixed validation metrics and gates for v22 differential photometry."""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
from sklearn.neighbors import NearestNeighbors


@dataclass(frozen=True, slots=True)
class PredictionRow:
    row_index: int
    channel: str
    target_group: str
    observed_magnitude: float
    raw_control_magnitude: float
    v21_control_magnitude: float
    predicted_nuisance: float
    corrected_magnitude: float
    status: str
    diagnostic_features: tuple[float, ...]
    planet_like: bool


@dataclass(frozen=True, slots=True)
class ChannelMetrics:
    sample_count: int
    raw_mae: float
    v21_mae: float
    corrected_mae: float
    raw_robust_scatter: float
    v21_robust_scatter: float
    corrected_robust_scatter: float
    raw_mae_improvement: float
    v21_mae_improvement: float
    raw_scatter_improvement: float
    v21_scatter_improvement: float
    bootstrap_lower_improvement: float
    planet_like_degradation: float


@dataclass(frozen=True, slots=True)
class TrendMetric:
    feature_name: str
    raw_slope: float
    v21_slope: float
    corrected_slope: float
    raw_interval: tuple[float, float]
    v21_interval: tuple[float, float]
    corrected_interval: tuple[float, float]
    passed: bool


@dataclass(frozen=True, slots=True)
class GateReport:
    passed: bool
    failures: tuple[str, ...]
    by_channel: Mapping[str, ChannelMetrics]
    trends: tuple[TrendMetric, ...]
    median_signal_attenuation: float


@dataclass(slots=True)
class TrainingSupport:
    lower: np.ndarray
    upper: np.ndarray
    centre: np.ndarray
    scale: np.ndarray
    neighbour_limit: float
    neighbours: NearestNeighbors

    @classmethod
    def fit(
        cls,
        features: np.ndarray,
        *,
        lower_quantile: float = 0.005,
        upper_quantile: float = 0.995,
        neighbour_quantile: float = 0.995,
        maximum_rows: int = 50_000,
    ) -> "TrainingSupport":
        array = np.asarray(features, dtype=float)
        if array.ndim != 2 or len(array) < 2 or not np.isfinite(array).all():
            raise ValueError("training support requires at least two finite rows")
        if len(array) > maximum_rows:
            indices = np.linspace(0, len(array) - 1, maximum_rows, dtype=int)
            array = array[indices]
        lower = np.quantile(array, lower_quantile, axis=0)
        upper = np.quantile(array, upper_quantile, axis=0)
        centre = np.median(array, axis=0)
        q25, q75 = np.quantile(array, (0.25, 0.75), axis=0)
        scale = q75 - q25
        scale[~np.isfinite(scale) | (scale <= 0.0)] = 1.0
        normalized = (array - centre) / scale
        neighbours = NearestNeighbors(n_neighbors=2).fit(normalized)
        distances = neighbours.kneighbors(normalized, return_distance=True)[0][:, 1]
        limit = float(np.quantile(distances, neighbour_quantile))
        return cls(lower, upper, centre, scale, max(limit, np.finfo(float).eps), neighbours)

    def status(self, features: np.ndarray) -> tuple[str, ...]:
        array = np.asarray(features, dtype=float)
        if array.ndim == 1:
            array = array.reshape(1, -1)
        if array.ndim != 2 or array.shape[1] != len(self.lower):
            raise ValueError("support feature width mismatch")
        output = []
        for row in array:
            if not np.isfinite(row).all() or np.any(row < self.lower) or np.any(row > self.upper):
                output.append("out_of_domain")
                continue
            normalized = (row - self.centre) / self.scale
            distance = float(
                self.neighbours.kneighbors(normalized.reshape(1, -1), n_neighbors=1)[0][0, 0]
            )
            output.append("supported" if distance <= self.neighbour_limit else "out_of_domain")
        return tuple(output)


def _mae(values: np.ndarray) -> float:
    return float(np.mean(np.abs(values))) if len(values) else math.nan


def _scatter(values: np.ndarray) -> float:
    if not len(values):
        return math.nan
    median = np.median(values)
    return float(1.4826 * np.median(np.abs(values - median)))


def _improvement(control: float, candidate: float) -> float:
    if not math.isfinite(control) or control <= 0.0 or not math.isfinite(candidate):
        return -math.inf
    return 1.0 - candidate / control


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    finite = np.isfinite(x) & np.isfinite(y)
    if finite.sum() < 3 or float(np.ptp(x[finite])) <= 0.0:
        return math.nan
    centred = x[finite] - np.median(x[finite])
    denominator = float(np.dot(centred, centred))
    return float(np.dot(centred, y[finite] - np.median(y[finite])) / denominator)


def _bootstrap_lower_improvement(
    rows: Sequence[PredictionRow], *, resamples: int, seed: int
) -> float:
    groups: dict[str, list[PredictionRow]] = {}
    for row in rows:
        groups.setdefault(row.target_group, []).append(row)
    names = sorted(groups)
    if len(names) < 2:
        return -math.inf
    group_errors = np.array(
        [
            (
                np.mean([abs(row.raw_control_magnitude) for row in groups[name]]),
                np.mean([abs(row.v21_control_magnitude) for row in groups[name]]),
                np.mean([abs(row.corrected_magnitude) for row in groups[name]]),
            )
            for name in names
        ],
        dtype=float,
    )
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(names), size=(resamples, len(names)))
    means = group_errors[draws].mean(axis=1)
    improvements = np.minimum(
        1.0 - means[:, 2] / means[:, 0],
        1.0 - means[:, 2] / means[:, 1],
    )
    return float(np.quantile(improvements, 0.025))


def _bootstrap_slope_interval(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    *,
    resamples: int,
    seed: int,
) -> tuple[float, float]:
    unique = np.unique(groups)
    if len(unique) < 3:
        return (math.nan, math.nan)
    group_x = np.array([np.nanmedian(x[groups == name]) for name in unique])
    group_y = np.array([np.nanmedian(y[groups == name]) for name in unique])
    finite = np.isfinite(group_x) & np.isfinite(group_y)
    group_x, group_y = group_x[finite], group_y[finite]
    if len(group_x) < 3:
        return (math.nan, math.nan)
    rng = np.random.default_rng(seed)
    slopes = []
    for _ in range(resamples):
        selected = rng.integers(0, len(group_x), size=len(group_x))
        value = _slope(group_x[selected], group_y[selected])
        if math.isfinite(value):
            slopes.append(value)
    if not slopes:
        return (math.nan, math.nan)
    return tuple(float(value) for value in np.quantile(slopes, (0.025, 0.975)))


def empirical_prediction_interval(
    residuals: np.ndarray, groups: np.ndarray, *, coverage: float = 0.90
) -> tuple[float, float]:
    residuals = np.asarray(residuals, dtype=float)
    groups = np.asarray(groups)
    if residuals.shape != groups.shape:
        raise ValueError("residual and group arrays must match")
    group_medians = np.array(
        [np.median(residuals[groups == name]) for name in np.unique(groups)], dtype=float
    )
    alpha = (1.0 - coverage) / 2.0
    return tuple(float(value) for value in np.quantile(group_medians, (alpha, 1.0 - alpha)))


def evaluate_gate(
    predictions: Sequence[PredictionRow],
    config: Mapping[str, object],
    *,
    diagnostic_feature_names: Sequence[str],
    signal_attenuations: Sequence[float],
) -> GateReport:
    required = float(config.get("improvement_fraction", 0.05))
    maximum_degradation = float(
        config.get("maximum_planet_stratum_degradation_fraction", 0.02)
    )
    maximum_attenuation = float(config.get("maximum_signal_attenuation_fraction", 0.05))
    resamples = int(config.get("bootstrap_resamples", 2000))
    seed = int(config.get("bootstrap_seed", 2203))
    usable = [
        row
        for row in predictions
        if row.status == "corrected"
        and all(
            math.isfinite(value)
            for value in (
                row.raw_control_magnitude,
                row.v21_control_magnitude,
                row.corrected_magnitude,
            )
        )
    ]
    failures: list[str] = []
    by_channel: dict[str, ChannelMetrics] = {}
    for channel in "RGB":
        rows = [row for row in usable if row.channel == channel]
        if not rows:
            failures.append(f"{channel}:no_eligible_validation_rows")
            continue
        raw = np.array([row.raw_control_magnitude for row in rows])
        v21 = np.array([row.v21_control_magnitude for row in rows])
        corrected = np.array([row.corrected_magnitude for row in rows])
        raw_mae, v21_mae, corrected_mae = _mae(raw), _mae(v21), _mae(corrected)
        raw_scatter, v21_scatter, corrected_scatter = (
            _scatter(raw),
            _scatter(v21),
            _scatter(corrected),
        )
        improvements = (
            _improvement(raw_mae, corrected_mae),
            _improvement(v21_mae, corrected_mae),
            _improvement(raw_scatter, corrected_scatter),
            _improvement(v21_scatter, corrected_scatter),
        )
        if min(improvements) < required:
            failures.append(f"{channel}:insufficient_error_or_scatter_improvement")
        bootstrap = _bootstrap_lower_improvement(rows, resamples=resamples, seed=seed + ord(channel))
        if bootstrap <= 0.0:
            failures.append(f"{channel}:bootstrap_improvement_not_positive")
        planet_rows = [row for row in rows if row.planet_like]
        if planet_rows:
            planet_candidate = _mae(
                np.array([row.corrected_magnitude for row in planet_rows])
            )
            planet_control = min(
                _mae(np.array([row.raw_control_magnitude for row in planet_rows])),
                _mae(np.array([row.v21_control_magnitude for row in planet_rows])),
            )
            degradation = planet_candidate / planet_control - 1.0 if planet_control > 0 else math.inf
        else:
            degradation = math.inf
        if degradation > maximum_degradation:
            failures.append(f"{channel}:planet_like_stratum_degraded")
        by_channel[channel] = ChannelMetrics(
            sample_count=len(rows),
            raw_mae=raw_mae,
            v21_mae=v21_mae,
            corrected_mae=corrected_mae,
            raw_robust_scatter=raw_scatter,
            v21_robust_scatter=v21_scatter,
            corrected_robust_scatter=corrected_scatter,
            raw_mae_improvement=improvements[0],
            v21_mae_improvement=improvements[1],
            raw_scatter_improvement=improvements[2],
            v21_scatter_improvement=improvements[3],
            bootstrap_lower_improvement=bootstrap,
            planet_like_degradation=degradation,
        )

    trends = []
    if usable:
        groups = np.array([row.target_group for row in usable])
        raw = np.array([row.raw_control_magnitude for row in usable])
        v21 = np.array([row.v21_control_magnitude for row in usable])
        corrected = np.array([row.corrected_magnitude for row in usable])
        for feature_index, name in enumerate(diagnostic_feature_names):
            x = np.array(
                [
                    row.diagnostic_features[feature_index]
                    if feature_index < len(row.diagnostic_features)
                    else math.nan
                    for row in usable
                ]
            )
            raw_slope = _slope(x, raw)
            v21_slope = _slope(x, v21)
            corrected_slope = _slope(x, corrected)
            raw_interval = _bootstrap_slope_interval(
                x, raw, groups, resamples=resamples, seed=seed + feature_index * 3
            )
            v21_interval = _bootstrap_slope_interval(
                x, v21, groups, resamples=resamples, seed=seed + feature_index * 3 + 1
            )
            corrected_interval = _bootstrap_slope_interval(
                x,
                corrected,
                groups,
                resamples=resamples,
                seed=seed + feature_index * 3 + 2,
            )
            raw_significant = all(math.isfinite(v) for v in raw_interval) and not (
                raw_interval[0] <= 0.0 <= raw_interval[1]
            )
            v21_significant = all(math.isfinite(v) for v in v21_interval) and not (
                v21_interval[0] <= 0.0 <= v21_interval[1]
            )
            if raw_significant or v21_significant:
                controls = [
                    abs(value)
                    for value, significant in (
                        (raw_slope, raw_significant),
                        (v21_slope, v21_significant),
                    )
                    if significant
                ]
                passed = math.isfinite(corrected_slope) and all(
                    abs(corrected_slope) <= (1.0 - required) * value for value in controls
                )
            else:
                passed = all(math.isfinite(v) for v in corrected_interval) and (
                    corrected_interval[0] <= 0.0 <= corrected_interval[1]
                )
            if not passed:
                failures.append(f"diagnostic_trend:{name}")
            trends.append(
                TrendMetric(
                    feature_name=name,
                    raw_slope=raw_slope,
                    v21_slope=v21_slope,
                    corrected_slope=corrected_slope,
                    raw_interval=raw_interval,
                    v21_interval=v21_interval,
                    corrected_interval=corrected_interval,
                    passed=passed,
                )
            )

    attenuation = (
        float(np.median(np.asarray(signal_attenuations, dtype=float)))
        if signal_attenuations
        else math.inf
    )
    if not math.isfinite(attenuation) or attenuation >= maximum_attenuation:
        failures.append("signal_attenuation")
    unique_failures = tuple(dict.fromkeys(failures))
    return GateReport(
        passed=not unique_failures,
        failures=unique_failures,
        by_channel=MappingProxyType(by_channel),
        trends=tuple(trends),
        median_signal_attenuation=attenuation,
    )
