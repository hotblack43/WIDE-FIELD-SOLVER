"""Read-only v22 benchmark orchestration and deterministic products."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
import hashlib
import json
import math
from pathlib import Path
import pickle
from typing import Mapping, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from v22.mmto_differential_data import (
    load_measurements,
    load_v21_control,
    write_input_audit,
)
from v22.mmto_differential_features import (
    FeatureTable,
    assign_splits,
    build_feature_table,
    write_feature_audit,
)
from v22.mmto_differential_metrics import GateReport, PredictionRow
from v22.mmto_differential_models import (
    ConfirmedModel,
    ValidationResult,
    confirm_on_test,
    fit_and_validate_candidates,
    reset_final_test_evaluation_count,
    select_simplest_passing,
)
from v22.mmto_planet_relative_photometry import (
    CorrectedPlanetMeasurement,
    apply_to_planets,
)


FIGURES = (
    "residual_diagnostics.pdf",
    "model_comparison.pdf",
    "signal_recovery.pdf",
    "planet_relative_lightcurves.pdf",
)
PDF_METADATA = {
    "Title": "V22 differential photometry benchmark",
    "Author": "Wide-Field Solver",
    "Creator": "Wide-Field Solver v0.22.0",
    "CreationDate": None,
    "ModDate": None,
}


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    status: str
    selected_method: str | None
    correction_available: bool
    validation_gate: str
    final_test_gate: str
    run_count: int
    stellar_measurement_count: int
    planet_measurement_count: int
    corrected_planet_count: int
    model_artifact: str | None
    model_sha256: str | None
    figures: tuple[str, ...]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_output(output: Path) -> None:
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            raise FileExistsError(f"benchmark output must be absent or empty: {output}")
    else:
        output.mkdir(parents=True)


def _read_run_ids(path: Path) -> frozenset[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.casefold() == ".json":
        values = json.loads(text)
        if isinstance(values, dict):
            values = values.get("run_ids")
        if not isinstance(values, list):
            raise ValueError("run-ID JSON must contain a list")
        result = frozenset(str(value) for value in values)
    elif "," in text.splitlines()[0]:
        result = frozenset(
            str(row["run_id"]).strip()
            for row in csv.DictReader(text.splitlines())
            if str(row.get("run_id", "")).strip()
        )
    else:
        result = frozenset(line.strip() for line in text.splitlines() if line.strip())
    if not result:
        raise ValueError("run-ID replay list is empty")
    return result


def _channel_dict(value) -> dict[str, object]:
    return {field.name: getattr(value, field.name) for field in fields(value)}


def _gate_dict(report: GateReport) -> dict[str, object]:
    return {
        "passed": report.passed,
        "failures": list(report.failures),
        "median_signal_attenuation": report.median_signal_attenuation,
        "by_channel": {
            channel: _channel_dict(metrics)
            for channel, metrics in sorted(report.by_channel.items())
        },
        "trends": [_channel_dict(trend) for trend in report.trends],
    }


def _write_validation(
    results: Sequence[ValidationResult], output: Path
) -> None:
    payload = [
        {
            "name": result.name,
            "gate_status": result.gate_status,
            "metrics": _gate_dict(result.metrics),
            "chosen_parameters": {
                channel: dict(values)
                for channel, values in sorted(
                    result.fitted_pipeline.chosen_parameters.items()
                )
            },
        }
        for result in results
    ]
    (output / "validation_metrics.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=True) + "\n",
        encoding="utf-8",
    )
    with (output / "validation_metrics.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        fieldnames = (
            "method",
            "gate_status",
            "channel",
            "sample_count",
            "raw_mae",
            "v21_mae",
            "corrected_mae",
            "raw_robust_scatter",
            "v21_robust_scatter",
            "corrected_robust_scatter",
            "raw_mae_improvement",
            "v21_mae_improvement",
            "raw_scatter_improvement",
            "v21_scatter_improvement",
            "bootstrap_lower_improvement",
            "planet_like_degradation",
            "failures",
        )
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            for channel, metrics in sorted(result.metrics.by_channel.items()):
                row = _channel_dict(metrics)
                writer.writerow(
                    {
                        "method": result.name,
                        "gate_status": result.gate_status,
                        "channel": channel,
                        **row,
                        "failures": ";".join(result.metrics.failures),
                    }
                )


def _write_predictions(results: Sequence[ValidationResult], output: Path) -> None:
    with (output / "fake_planet_predictions.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        fieldnames = ("method",) + tuple(field.name for field in fields(PredictionRow))
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            for row in result.validation_predictions:
                writer.writerow({"method": result.name, **asdict(row)})


def _write_signals(results: Sequence[ValidationResult], output: Path) -> None:
    with (output / "signal_recovery.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        fieldnames = (
            "method",
            "row_index",
            "role",
            "signal_type",
            "injected_signal_magnitude",
            "recovered_signal_magnitude",
            "attenuation_fraction",
            "status",
        )
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            for row in result.signal_recovery:
                writer.writerow({"method": result.name, **asdict(row)})


def _write_planets(
    rows: Sequence[CorrectedPlanetMeasurement], output: Path
) -> None:
    with (output / "planet_relative_photometry.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        fieldnames = tuple(field.name for field in fields(CorrectedPlanetMeasurement))
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _save_figure(figure, path: Path) -> None:
    figure.savefig(path, metadata=PDF_METADATA, bbox_inches="tight")
    plt.close(figure)


def _plot_residuals(results: Sequence[ValidationResult], output: Path) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(12, 4), sharey=True)
    selected = next((result for result in results if result.gate_status == "passed"), None)
    for axis, channel in zip(axes, "RGB", strict=True):
        rows = [
            row
            for row in (selected.validation_predictions if selected else ())
            if row.channel == channel and row.status == "corrected"
        ]
        if rows:
            x = np.arange(len(rows))
            axis.plot(x, [row.raw_control_magnitude for row in rows], ".", label="raw", alpha=0.6)
            axis.plot(x, [row.v21_control_magnitude for row in rows], ".", label="v21", alpha=0.6)
            axis.plot(x, [row.corrected_magnitude for row in rows], ".", label="v22", alpha=0.6)
        else:
            axis.text(0.5, 0.5, "No passing validation model", ha="center", va="center", transform=axis.transAxes)
        axis.set_title(channel)
        axis.set_xlabel("Validation row")
        axis.grid(alpha=0.2)
    axes[0].set_ylabel("Centred residual (mag)")
    handles, labels = axes[0].get_legend_handles_labels()
    figure.suptitle("Held-out pseudo-planet residuals", y=0.99)
    if handles:
        figure.legend(
            handles,
            labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.93),
            ncol=3,
        )
    figure.tight_layout(rect=(0, 0, 1, 0.84))
    _save_figure(figure, output / "residual_diagnostics.pdf")


def _plot_models(results: Sequence[ValidationResult], output: Path) -> None:
    figure, axis = plt.subplots(figsize=(9, 5))
    x = np.arange(len(results))
    width = 0.24
    for offset, channel in enumerate("RGB"):
        values = [
            result.metrics.by_channel[channel].corrected_mae
            if channel in result.metrics.by_channel
            else math.nan
            for result in results
        ]
        axis.bar(x + (offset - 1) * width, values, width, label=channel)
    axis.set_xticks(x, [result.name.replace("_", "\n") for result in results])
    axis.set_ylabel("Validation MAE (mag)")
    axis.set_title("Fixed-order model comparison")
    axis.grid(axis="y", alpha=0.2)
    axis.legend(loc="upper left", bbox_to_anchor=(1.01, 1.0))
    figure.tight_layout(rect=(0, 0, 0.91, 1))
    _save_figure(figure, output / "model_comparison.pdf")


def _plot_signals(results: Sequence[ValidationResult], output: Path) -> None:
    figure, axis = plt.subplots(figsize=(7, 6))
    all_values = []
    for result in results:
        rows = [
            row
            for row in result.signal_recovery
            if math.isfinite(row.recovered_signal_magnitude)
        ]
        if len(rows) > 5000:
            indices = np.linspace(0, len(rows) - 1, 5000, dtype=int)
            rows = [rows[index] for index in indices]
        injected = np.asarray(
            [row.injected_signal_magnitude for row in rows], dtype=float
        )
        recovered = np.asarray(
            [row.recovered_signal_magnitude for row in rows], dtype=float
        )
        if len(injected):
            all_values.extend(injected.tolist())
            all_values.extend(recovered.tolist())
            axis.scatter(injected, recovered, s=7, alpha=0.25, label=result.name)
    if all_values:
        values = np.asarray(all_values, dtype=float)
        limits = (float(values.min()), float(values.max()))
        axis.plot(limits, limits, "k--", linewidth=1, label="perfect recovery")
        axis.legend(fontsize=8)
    else:
        axis.text(0.5, 0.5, "No measured injected rows", ha="center", va="center", transform=axis.transAxes)
    axis.set(xlabel="Injected signal (mag)", ylabel="Recovered signal (mag)", title="Measured validation signal preservation")
    axis.grid(alpha=0.2)
    figure.tight_layout()
    _save_figure(figure, output / "signal_recovery.pdf")


def _plot_planets(rows: Sequence[CorrectedPlanetMeasurement], output: Path) -> None:
    figure, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    for axis, channel in zip(axes, "RGB", strict=True):
        selected = [row for row in rows if row.channel == channel]
        for identity in sorted({row.identity_name for row in selected})[:8]:
            series = [row for row in selected if row.identity_name == identity]
            x = np.arange(len(series))
            axis.plot(x, [row.raw_machine_magnitude for row in series], ".-", alpha=0.45, label=f"{identity} raw")
            axis.plot(x, [row.v21_control_magnitude for row in series], ".-", alpha=0.45, label=f"{identity} v21")
            if any(
                row.v22_relative_magnitude is not None
                and math.isfinite(row.v22_relative_magnitude)
                for row in series
            ):
                axis.plot(x, [row.v22_relative_magnitude for row in series], "o-", alpha=0.8, label=f"{identity} v22")
        if not selected:
            axis.text(0.5, 0.5, "No planet rows", ha="center", va="center", transform=axis.transAxes)
        axis.set_ylabel(f"{channel} mag")
        axis.grid(alpha=0.2)
    axes[-1].set_xlabel("Observation order")
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        figure.legend(
            handles[:12],
            labels[:12],
            loc="upper center",
            bbox_to_anchor=(0.5, 0.955),
            ncol=4,
            fontsize=7,
        )
    has_v22 = any(
        row.v22_relative_magnitude is not None
        and math.isfinite(row.v22_relative_magnitude)
        for row in rows
    )
    figure.suptitle(
        "Planet relative photometry: raw, v21 control, and confirmed v22"
        if has_v22
        else "Planet relative photometry: raw and v21 control; no v22 correction passed",
        y=0.995,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.86))
    _save_figure(figure, output / "planet_relative_lightcurves.pdf")


def _serialize_model(model: ConfirmedModel, output: Path) -> tuple[str, str]:
    fitted = model.fitted_pipeline
    if fitted.name == "local_ensemble":
        name = "confirmed_model.json"
        payload = {
            "schema_version": 1,
            "method": fitted.name,
            "feature_names": list(fitted.feature_names),
            "algorithm": "smallest supported 128/256/512 px median, then exposure median",
            "test_metrics": _gate_dict(model.test_metrics),
        }
        (output / name).write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=True) + "\n",
            encoding="utf-8",
        )
    else:
        name = "confirmed_model.pkl"
        payload = {
            "schema_version": 1,
            "method": fitted.name,
            "feature_names": fitted.feature_names,
            "estimators": dict(fitted.estimators),
            "support": dict(fitted.support),
            "support_medians": dict(fitted.support_medians),
            "prediction_intervals": dict(fitted.prediction_intervals),
            "chosen_parameters": {
                key: dict(value) for key, value in fitted.chosen_parameters.items()
            },
        }
        (output / name).write_bytes(pickle.dumps(payload, protocol=5))
    return name, _sha256(output / name)


def run_benchmark(
    database: Path,
    manifest: Path,
    v21_control: Path,
    output: Path,
    config: Path,
    *,
    run_ids: Path | None = None,
) -> BenchmarkSummary:
    output = Path(output)
    _prepare_output(output)
    configuration = json.loads(Path(config).read_text(encoding="utf-8"))
    if not isinstance(configuration, dict):
        raise ValueError("benchmark configuration must be a JSON object")
    control = load_v21_control(Path(v21_control))
    selected_ids = _read_run_ids(Path(run_ids)) if run_ids else control.selected_run_ids
    data = load_measurements(
        Path(database), Path(manifest), run_ids=frozenset(selected_ids)
    )
    splits = assign_splits(data, seed=int(configuration.get("seed_features", 2201)))
    table = build_feature_table(data, control, splits, configuration)
    write_input_audit(data, output)
    write_feature_audit(table, output)
    reset_final_test_evaluation_count()
    results = fit_and_validate_candidates(table, configuration)
    selected = select_simplest_passing(results)
    confirmed = confirm_on_test(selected, table, configuration) if selected else None
    planets = apply_to_planets(confirmed, data.planets, table)
    _write_validation(results, output)
    _write_predictions(results, output)
    _write_signals(results, output)
    _write_planets(planets, output)
    _plot_residuals(results, output)
    _plot_models(results, output)
    _plot_signals(results, output)
    _plot_planets(planets, output)
    artifact = model_hash = None
    if confirmed is not None:
        artifact, model_hash = _serialize_model(confirmed, output)
    summary = BenchmarkSummary(
        status="complete",
        selected_method=selected.name if selected else None,
        correction_available=confirmed is not None,
        validation_gate=(selected.gate_status if selected else "no_method_passed"),
        final_test_gate=("passed" if confirmed is not None else "failed" if selected else "not_opened"),
        run_count=len(data.runs),
        stellar_measurement_count=len(data.stellar),
        planet_measurement_count=len(data.planets),
        corrected_planet_count=sum(row.correction_status == "corrected" for row in planets),
        model_artifact=artifact,
        model_sha256=model_hash,
        figures=FIGURES,
    )
    (output / "benchmark_summary.json").write_text(
        json.dumps(asdict(summary), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
