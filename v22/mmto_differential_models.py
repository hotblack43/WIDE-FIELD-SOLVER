"""Fixed-order candidate fitting and one-shot final confirmation for v22."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import GroupKFold
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from v22.mmto_differential_features import FeatureRow, FeatureTable
from v22.mmto_differential_metrics import (
    GateReport,
    PredictionRow,
    TrainingSupport,
    empirical_prediction_interval,
    evaluate_gate,
)


ORDER = ("local_ensemble", "random_forest", "gradient_boosting", "neural_network")
_FINAL_TEST_EVALUATIONS = 0


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    name: str
    parameters: Mapping[str, object]


@dataclass(slots=True)
class FittedCandidate:
    name: str
    feature_names: tuple[str, ...]
    estimators: Mapping[str, object]
    support: Mapping[str, TrainingSupport]
    prediction_intervals: Mapping[str, tuple[float, float]]
    support_medians: Mapping[str, np.ndarray] = field(
        default_factory=lambda: MappingProxyType({})
    )
    chosen_parameters: Mapping[str, Mapping[str, object]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    test_evaluated: bool = False


@dataclass(frozen=True, slots=True)
class ValidationResult:
    name: str
    metrics: GateReport
    gate_status: str
    fitted_pipeline: FittedCandidate
    validation_predictions: tuple[PredictionRow, ...]


@dataclass(frozen=True, slots=True)
class ConfirmedModel:
    name: str
    fitted_pipeline: FittedCandidate
    test_metrics: GateReport
    test_predictions: tuple[PredictionRow, ...]


def candidate_specs(config: Mapping[str, object]) -> tuple[CandidateSpec, ...]:
    return (
        CandidateSpec("local_ensemble", MappingProxyType({})),
        CandidateSpec(
            "random_forest",
            MappingProxyType(
                {
                    "n_estimators": int(config.get("random_forest_trees", 300)),
                    "max_features": 0.7,
                    "min_samples_leaf": tuple(
                        int(value)
                        for value in config.get(
                            "random_forest_min_samples_leaf", (8, 20)
                        )
                    ),
                }
            ),
        ),
        CandidateSpec(
            "gradient_boosting",
            MappingProxyType(
                {
                    "max_iter": int(config.get("gradient_boosting_iterations", 300)),
                    "learning_rate": 0.05,
                    "l2_regularization": 1.0,
                    "max_leaf_nodes": tuple(
                        int(value)
                        for value in config.get(
                            "gradient_boosting_leaf_counts", (15, 31)
                        )
                    ),
                }
            ),
        ),
        CandidateSpec(
            "neural_network",
            MappingProxyType(
                {
                    "hidden_layer_sizes": tuple(
                        tuple(int(node) for node in value)
                        for value in config.get(
                            "mlp_hidden_layers", ((32,), (32, 16))
                        )
                    ),
                    "alpha": tuple(float(value) for value in config.get("mlp_alpha", (1e-4, 1e-3))),
                    "max_iter": int(config.get("mlp_max_iterations", 500)),
                    "early_stopping": True,
                }
            ),
        ),
    )


def local_ensemble_prediction(
    row: FeatureRow, *, minimum_local: int = 12, minimum_exposure: int = 30
) -> tuple[float, str]:
    for median, count in (
        (row.local_median_128_px, row.local_count_128_px),
        (row.local_median_256_px, row.local_count_256_px),
        (row.local_median_512_px, row.local_count_512_px),
    ):
        if count >= minimum_local and math.isfinite(median):
            return median, "corrected"
    if row.exposure_count >= minimum_exposure and math.isfinite(
        row.exposure_median_magnitude
    ):
        return row.exposure_median_magnitude, "corrected"
    return math.nan, "insufficient_local_stars"


def _limited_rows(rows: Sequence[FeatureRow], maximum: int) -> list[FeatureRow]:
    if len(rows) <= maximum:
        return list(rows)
    indices = np.linspace(0, len(rows) - 1, maximum, dtype=int)
    return [rows[index] for index in indices]


def _model(spec: CandidateSpec, parameter: Mapping[str, object], seed: int):
    if spec.name == "random_forest":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=int(spec.parameters["n_estimators"]),
                        max_features=float(spec.parameters["max_features"]),
                        min_samples_leaf=int(parameter["min_samples_leaf"]),
                        random_state=seed,
                        n_jobs=-1,
                    ),
                ),
            ]
        )
    if spec.name == "gradient_boosting":
        return HistGradientBoostingRegressor(
            max_iter=int(spec.parameters["max_iter"]),
            learning_rate=float(spec.parameters["learning_rate"]),
            l2_regularization=float(spec.parameters["l2_regularization"]),
            max_leaf_nodes=int(parameter["max_leaf_nodes"]),
            random_state=seed,
        )
    if spec.name == "neural_network":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("standardize", StandardScaler()),
                (
                    "model",
                    MLPRegressor(
                        hidden_layer_sizes=tuple(parameter["hidden_layer_sizes"]),
                        alpha=float(parameter["alpha"]),
                        max_iter=int(spec.parameters["max_iter"]),
                        early_stopping=bool(spec.parameters["early_stopping"]),
                        random_state=seed,
                    ),
                ),
            ]
        )
    raise ValueError(f"unknown fitted candidate: {spec.name}")


def _parameter_grid(spec: CandidateSpec) -> tuple[Mapping[str, object], ...]:
    if spec.name == "random_forest":
        return tuple(
            {"min_samples_leaf": value}
            for value in spec.parameters["min_samples_leaf"]
        )
    if spec.name == "gradient_boosting":
        return tuple(
            {"max_leaf_nodes": value} for value in spec.parameters["max_leaf_nodes"]
        )
    if spec.name == "neural_network":
        return tuple(
            {"hidden_layer_sizes": layers, "alpha": alpha}
            for layers in spec.parameters["hidden_layer_sizes"]
            for alpha in spec.parameters["alpha"]
        )
    return ({},)


def _matrix(rows: Sequence[FeatureRow]) -> np.ndarray:
    return np.asarray([row.deployable_features for row in rows], dtype=float)


def _fit_channel(
    spec: CandidateSpec,
    rows: Sequence[FeatureRow],
    *,
    seed: int,
    maximum_tuning_rows: int,
    maximum_training_rows: int,
) -> tuple[object, Mapping[str, object], TrainingSupport, np.ndarray]:
    tuning = _limited_rows(rows, maximum_tuning_rows)
    parameters = _parameter_grid(spec)
    groups = np.asarray([row.night for row in tuning])
    unique_groups = np.unique(groups)
    best = parameters[0]
    best_score = math.inf
    if len(unique_groups) >= 2:
        folds = GroupKFold(n_splits=min(3, len(unique_groups)))
        x_tuning = _matrix(tuning)
        y_tuning = np.asarray([row.target_delta_magnitude for row in tuning])
        for choice in parameters:
            scores = []
            for train_indices, validation_indices in folds.split(
                x_tuning, y_tuning, groups
            ):
                estimator = _model(spec, choice, seed)
                estimator.fit(x_tuning[train_indices], y_tuning[train_indices])
                predicted = estimator.predict(x_tuning[validation_indices])
                scores.append(
                    mean_absolute_error(y_tuning[validation_indices], predicted)
                )
            score = float(np.mean(scores))
            if score < best_score:
                best_score, best = score, choice
    training = _limited_rows(rows, maximum_training_rows)
    x = _matrix(training)
    y = np.asarray([row.target_delta_magnitude for row in training])
    estimator = _model(spec, best, seed)
    estimator.fit(x, y)
    median = np.nanmedian(x, axis=0)
    median[~np.isfinite(median)] = 0.0
    support_x = np.where(np.isfinite(x), x, median)
    support = TrainingSupport.fit(support_x)
    return estimator, MappingProxyType(dict(best)), support, median


def _fit_candidate(
    spec: CandidateSpec, table: FeatureTable, config: Mapping[str, object]
) -> FittedCandidate:
    if spec.name == "local_ensemble":
        return FittedCandidate(
            name=spec.name,
            feature_names=table.deployable_feature_names,
            estimators=MappingProxyType({}),
            support=MappingProxyType({}),
            prediction_intervals=MappingProxyType({}),
        )
    estimators = {}
    supports = {}
    medians = {}
    choices = {}
    maximum_tuning = int(config.get("maximum_tuning_rows_per_channel", 10_000))
    maximum_training = int(config.get("maximum_training_rows_per_channel", 50_000))
    seed = int(config.get("model_seed", 2204))
    for channel in "RGB":
        rows = [row for row in table.rows if row.role == "train" and row.channel == channel]
        if len(rows) < 2:
            continue
        estimator, choice, support, median = _fit_channel(
            spec,
            rows,
            seed=seed + ord(channel),
            maximum_tuning_rows=maximum_tuning,
            maximum_training_rows=maximum_training,
        )
        estimators[channel] = estimator
        supports[channel] = support
        medians[channel] = median
        choices[channel] = choice
    return FittedCandidate(
        name=spec.name,
        feature_names=table.deployable_feature_names,
        estimators=MappingProxyType(estimators),
        support=MappingProxyType(supports),
        prediction_intervals=MappingProxyType({}),
        support_medians=MappingProxyType(medians),
        chosen_parameters=MappingProxyType(choices),
    )


def _predictions(
    candidate: FittedCandidate,
    rows: Sequence[FeatureRow],
    config: Mapping[str, object],
    planet_ranges: Mapping[str, tuple[float, float, float, float]] | None = None,
) -> tuple[PredictionRow, ...]:
    predicted_values = np.full(len(rows), math.nan, dtype=float)
    statuses = np.full(len(rows), "model_unavailable", dtype=object)
    minimum_local = int(config.get("minimum_local_comparisons", 12))
    minimum_exposure = int(config.get("minimum_exposure_comparisons", 30))
    if candidate.name == "local_ensemble":
        for index, row in enumerate(rows):
            predicted, status = local_ensemble_prediction(
                row,
                minimum_local=minimum_local,
                minimum_exposure=minimum_exposure,
            )
            predicted_values[index] = predicted
            statuses[index] = status
    else:
        for channel in "RGB":
            indices = [index for index, row in enumerate(rows) if row.channel == channel]
            if not indices or channel not in candidate.estimators:
                continue
            raw = np.asarray(
                [rows[index].deployable_features for index in indices], dtype=float
            )
            median = candidate.support_medians[channel]
            support_values = np.where(np.isfinite(raw), raw, median)
            support_status = np.asarray(
                candidate.support[channel].status(support_values), dtype=object
            )
            supported = support_status == "supported"
            statuses[np.asarray(indices)] = support_status
            if supported.any():
                supported_indices = np.asarray(indices)[supported]
                predicted_values[supported_indices] = candidate.estimators[channel].predict(
                    raw[supported]
                )
                statuses[supported_indices] = "corrected"

    staged = []
    grouped_corrected: dict[str, list[float]] = {}
    for index, row in enumerate(rows):
        predicted = float(predicted_values[index])
        status = str(statuses[index])
        corrected = (
            row.target_delta_magnitude - predicted
            if status == "corrected" and math.isfinite(predicted)
            else math.nan
        )
        target_group = f"{row.catalogue_sha256}:{row.star_id}:{row.channel}"
        staged.append((index, row, predicted, status, corrected, target_group))
        if math.isfinite(corrected):
            grouped_corrected.setdefault(target_group, []).append(corrected)
    centres = {
        target_group: float(np.median(values))
        for target_group, values in grouped_corrected.items()
    }
    output = []
    for index, row, predicted, status, corrected, target_group in staged:
        metric_corrected = (
            corrected - centres[target_group]
            if math.isfinite(corrected) and target_group in centres
            else math.nan
        )
        planet_like = True
        if planet_ranges and row.channel in planet_ranges:
            minimum_magnitude, maximum_magnitude, minimum_radius, maximum_radius = planet_ranges[
                row.channel
            ]
            magnitude = row.diagnostic_features[0]
            radius = row.diagnostic_features[4]
            planet_like = (
                minimum_magnitude <= magnitude <= maximum_magnitude
                and minimum_radius <= radius <= maximum_radius
            )
        output.append(
            PredictionRow(
                row_index=index,
                channel=row.channel,
                target_group=target_group,
                observed_magnitude=row.target_delta_magnitude,
                raw_control_magnitude=row.raw_control_magnitude,
                v21_control_magnitude=row.v21_control_magnitude,
                predicted_nuisance=predicted,
                corrected_magnitude=metric_corrected,
                status=status,
                diagnostic_features=row.diagnostic_features,
                planet_like=planet_like,
            )
        )
    return tuple(output)


def _planet_ranges(
    table: FeatureTable,
) -> Mapping[str, tuple[float, float, float, float]]:
    grouped: dict[str, list[tuple[float, float]]] = {}
    for row in table.data.planets if table.data is not None else ():
        if (
            row.valid_measurement
            and row.machine_magnitude is not None
            and row.x_px is not None
            and row.y_px is not None
        ):
            x = (row.x_px - row.image_width_px / 2.0) / max(row.image_width_px / 2.0, 1.0)
            y = (row.y_px - row.image_height_px / 2.0) / max(row.image_height_px / 2.0, 1.0)
            grouped.setdefault(row.channel, []).append(
                (row.machine_magnitude, math.hypot(x, y))
            )
    return MappingProxyType(
        {
            channel: (
                min(value[0] for value in values),
                max(value[0] for value in values),
                min(value[1] for value in values),
                max(value[1] for value in values),
            )
            for channel, values in grouped.items()
        }
    )


def _intervals(
    predictions: Sequence[PredictionRow],
) -> Mapping[str, tuple[float, float]]:
    result = {}
    for channel in "RGB":
        rows = [
            row
            for row in predictions
            if row.channel == channel and row.status == "corrected"
        ]
        if not rows:
            continue
        residuals = np.asarray(
            [row.observed_magnitude - row.predicted_nuisance for row in rows]
        )
        groups = np.asarray([row.target_group for row in rows])
        result[channel] = empirical_prediction_interval(residuals, groups, coverage=0.90)
    return MappingProxyType(result)


def fit_and_validate_candidates(
    table: FeatureTable, config: Mapping[str, object]
) -> tuple[ValidationResult, ...]:
    validation_rows = [row for row in table.rows if row.role == "validation"]
    planet_ranges = _planet_ranges(table)
    output = []
    for spec in candidate_specs(config):
        fitted = _fit_candidate(spec, table, config)
        predictions = _predictions(fitted, validation_rows, config, planet_ranges)
        fitted.prediction_intervals = _intervals(predictions)
        metrics = evaluate_gate(
            predictions,
            config,
            diagnostic_feature_names=table.diagnostic_feature_names,
            signal_attenuations=(0.0,),
        )
        output.append(
            ValidationResult(
                name=spec.name,
                metrics=metrics,
                gate_status="passed" if metrics.passed else "failed",
                fitted_pipeline=fitted,
                validation_predictions=predictions,
            )
        )
    return tuple(output)


def select_simplest_passing(
    results: Sequence[ValidationResult],
) -> ValidationResult | None:
    by_name = {result.name: result for result in results}
    for name in ORDER:
        result = by_name.get(name)
        if result is not None and result.gate_status == "passed" and result.metrics.passed:
            return result
    return None


def confirm_on_test(
    selected: ValidationResult,
    table: FeatureTable | None,
    config: Mapping[str, object],
) -> ConfirmedModel | None:
    global _FINAL_TEST_EVALUATIONS
    if selected.fitted_pipeline.test_evaluated:
        raise RuntimeError("selected candidate final test already evaluated")
    selected.fitted_pipeline.test_evaluated = True
    _FINAL_TEST_EVALUATIONS += 1
    if bool(config.get("force_test_failure", False)) or table is None:
        return None
    test_rows = [row for row in table.rows if row.role == "test"]
    predictions = _predictions(
        selected.fitted_pipeline, test_rows, config, _planet_ranges(table)
    )
    metrics = evaluate_gate(
        predictions,
        config,
        diagnostic_feature_names=table.diagnostic_feature_names,
        signal_attenuations=(0.0,),
    )
    if not metrics.passed:
        return None
    return ConfirmedModel(
        name=selected.name,
        fitted_pipeline=selected.fitted_pipeline,
        test_metrics=metrics,
        test_predictions=predictions,
    )


def final_test_evaluation_count() -> int:
    return _FINAL_TEST_EVALUATIONS


def reset_final_test_evaluation_count() -> None:
    global _FINAL_TEST_EVALUATIONS
    _FINAL_TEST_EVALUATIONS = 0
