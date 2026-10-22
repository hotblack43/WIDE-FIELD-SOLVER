"""Read-only, auditable inputs for v22 differential photometry.

The loader replays an explicit v21 run population when supplied.  It never
writes either SQLite input and fails closed when saved products cannot be
joined one-to-one.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from types import MappingProxyType
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo


CHANNELS = ("R", "G", "B")
ARIZONA = ZoneInfo("America/Phoenix")
PACKAGE = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    recorded_at_utc: str
    source_path: str
    source_sha256: str
    analysis_path: str
    solver_version: str
    catalogue_sha256: str
    observed_utc: str
    night: str
    width_px: int
    height_px: int
    global_noise_adu: float | None
    exposure_seconds: float | None


@dataclass(frozen=True, slots=True)
class StellarMeasurement:
    run_id: str
    source_sha256: str
    observed_utc: str
    night: str
    catalogue_sha256: str
    star_id: str
    detection_id: str
    channel: str
    catalogue_magnitude: float
    count_rate_adu_per_s: float
    machine_magnitude: float
    airmass: float
    x_px: float
    y_px: float
    image_width_px: int
    image_height_px: int
    source_class: str
    exposure_seconds: float | None
    flux_adu: float | None
    saturation_known: bool
    saturated: bool
    measurement_method: str
    area_px: float | None
    major_sigma_px: float | None
    axis_ratio: float | None
    peak_snr: float | None
    aperture_radius_px: float | None
    aperture_background_adu: float | None
    global_noise_adu: float | None
    gaia_bp_magnitude: float | None
    gaia_rp_magnitude: float | None
    gaia_bp_minus_rp: float | None

    def deployable_features(self) -> dict[str, float]:
        """Return only saved target-independent features usable for planets."""

        values = {
            "x_px": self.x_px,
            "y_px": self.y_px,
            "image_width_px": float(self.image_width_px),
            "image_height_px": float(self.image_height_px),
            "airmass": self.airmass,
            "exposure_seconds": self.exposure_seconds,
            "area_px": self.area_px,
            "major_sigma_px": self.major_sigma_px,
            "axis_ratio": self.axis_ratio,
            "peak_snr": self.peak_snr,
            "aperture_radius_px": self.aperture_radius_px,
            "aperture_background_adu": self.aperture_background_adu,
            "global_noise_adu": self.global_noise_adu,
        }
        return {name: float(value) for name, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True)
class PlanetMeasurement:
    run_id: str
    source_sha256: str
    observed_utc: str
    night: str
    identity_type: str
    identity_name: str
    identity_status: str
    candidate_rank: int | None
    epoch_tdb: str | None
    detection_id: str
    channel: str
    count_rate_adu_per_s: float | None
    machine_magnitude: float | None
    x_px: float | None
    y_px: float | None
    image_width_px: int
    image_height_px: int
    source_class: str
    exposure_seconds: float | None
    flux_adu: float | None
    saturation_known: bool | None
    saturated: bool | None
    measurement_method: str
    area_px: float | None
    major_sigma_px: float | None
    axis_ratio: float | None
    peak_snr: float | None
    aperture_radius_px: float | None
    aperture_background_adu: float | None
    global_noise_adu: float | None
    valid_measurement: bool
    exclusion_reasons: tuple[str, ...]

    def deployable_features(self) -> dict[str, float]:
        values = {
            "x_px": self.x_px,
            "y_px": self.y_px,
            "image_width_px": float(self.image_width_px),
            "image_height_px": float(self.image_height_px),
            "exposure_seconds": self.exposure_seconds,
            "area_px": self.area_px,
            "major_sigma_px": self.major_sigma_px,
            "axis_ratio": self.axis_ratio,
            "peak_snr": self.peak_snr,
            "aperture_radius_px": self.aperture_radius_px,
            "aperture_background_adu": self.aperture_background_adu,
            "global_noise_adu": self.global_noise_adu,
        }
        return {name: float(value) for name, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True)
class AuditRow:
    row_type: str
    run_id: str
    source_sha256: str
    star_id: str
    detection_id: str
    identity_name: str
    channel: str
    included: bool
    exclusion_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MeasurementSet:
    runs: tuple[RunRecord, ...]
    stellar: tuple[StellarMeasurement, ...]
    planets: tuple[PlanetMeasurement, ...]
    audit: tuple[AuditRow, ...]
    database_path: str
    manifest_path: str
    database_sha256: str
    manifest_sha256: str
    input_solver_version: str


@dataclass(frozen=True, slots=True)
class V21Control:
    selected_run_ids: frozenset[str]
    adopted_model: str
    corrected_magnitudes: Mapping[tuple[str, str, str, str], float]
    extinction_coefficients: Mapping[tuple[str, str, str], float]
    manifest_sha256: str
    corrected_photometry_sha256: str
    coefficients_sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _positive(value: object) -> float | None:
    number = _finite(value)
    return number if number is not None and number > 0.0 else None


def _boolean(value: object) -> bool | None:
    text = str(value).strip().casefold()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _integer(value: object) -> int | None:
    number = _finite(value)
    return int(number) if number is not None and number.is_integer() else None


def _night(observed_utc: str) -> str:
    local = datetime.fromisoformat(observed_utc.replace("Z", "+00:00")).astimezone(ARIZONA)
    day = local.date()
    if local.hour < 12:
        day = day.fromordinal(day.toordinal() - 1)
    return day.isoformat()


def _json_object(raw: object, *, label: str) -> dict[str, object]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        value = json.loads(str(raw))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ValueError(f"invalid JSON in {label}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid JSON object in {label}")
    return value


def _measurement_rows(
    connection: sqlite3.Connection, run_id: str, product: str
) -> list[tuple[int, str, str, dict[str, object]]]:
    rows = []
    for number, star_id, detection_id, raw in connection.execute(
        """SELECT row_number,star_id,detection_id,values_json
           FROM measurements WHERE run_id=? AND product=? ORDER BY row_number""",
        (run_id, product),
    ):
        rows.append(
            (
                int(number),
                str(star_id or ""),
                str(detection_id or ""),
                _json_object(raw, label=f"{run_id}:{product}:{number}"),
            )
        )
    return rows


def _unique_by_detection(
    rows: Sequence[tuple[int, str, str, dict[str, object]]], product: str
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for _, _, detection_id, values in rows:
        detection_id = detection_id or str(values.get("detection_id", ""))
        if not detection_id:
            raise ValueError(f"missing detection ID in {product}")
        if detection_id in result:
            raise ValueError(f"non-unique detection join in {product}: {detection_id}")
        result[detection_id] = values
    return result


def _unique_coordinates(
    rows: Sequence[tuple[int, str, str, dict[str, object]]]
) -> dict[tuple[str, str], dict[str, object]]:
    result: dict[tuple[str, str], dict[str, object]] = {}
    for _, star_id, detection_id, values in rows:
        star_id = star_id or str(values.get("star_id", ""))
        detection_id = detection_id or str(values.get("detection_id", ""))
        key = (star_id, detection_id)
        if not all(key):
            raise ValueError("missing stellar coordinate join key")
        if key in result:
            raise ValueError(f"non-unique detection join in star_coordinates.csv: {key}")
        result[key] = values
    return result


def _catalogue_colours(catalogue_sha256: str) -> Mapping[str, tuple[float | None, float | None]]:
    catalogue = None
    for candidate in sorted((PACKAGE / "data").glob("*.csv")):
        if candidate.name.endswith(".gaia-source.csv"):
            continue
        if _sha256(candidate) == catalogue_sha256:
            catalogue = candidate
            break
    if catalogue is None:
        raise ValueError(f"catalogue bytes unavailable for hash {catalogue_sha256}")
    source = catalogue.with_suffix(".gaia-source.csv")
    if not source.is_file():
        return MappingProxyType({})
    colours: dict[str, tuple[float | None, float | None]] = {}
    with source.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            source_id = str(row.get("source_id", "")).strip()
            if source_id:
                colours[f"Gaia DR3 {source_id}"] = (
                    _finite(row.get("phot_bp_mean_mag")),
                    _finite(row.get("phot_rp_mean_mag")),
                )
    return MappingProxyType(colours)


def _aperture_radius(candidate: Mapping[str, object]) -> float | None:
    sigma = _positive(candidate.get("major_sigma_px"))
    return min(9.0, max(3.0, 2.5 * sigma)) if sigma is not None else None


def _audit(
    row_type: str,
    run_id: str,
    source_sha256: str,
    *,
    star_id: str = "",
    detection_id: str = "",
    identity_name: str = "",
    channel: str = "",
    reasons: Sequence[str] = (),
) -> AuditRow:
    unique = tuple(dict.fromkeys(reasons))
    return AuditRow(
        row_type=row_type,
        run_id=run_id,
        source_sha256=source_sha256,
        star_id=star_id,
        detection_id=detection_id,
        identity_name=identity_name,
        channel=channel,
        included=not unique,
        exclusion_reasons=unique,
    )


def _select_runs(
    connection: sqlite3.Connection,
    observations: Mapping[str, tuple[str, float]],
    *,
    input_solver_version: str,
    run_ids: frozenset[str] | None,
) -> tuple[list[tuple[object, ...]], list[AuditRow]]:
    columns = (
        "run_id,recorded_at_utc,source_path,source_sha256,analysis_path,"
        "exit_code,solver_version,catalogue_sha256"
    )
    if run_ids is None:
        all_rows = connection.execute(
            f"SELECT {columns} FROM runs WHERE solver_version=? "
            "ORDER BY recorded_at_utc,run_id",
            (input_solver_version,),
        ).fetchall()
    else:
        # An adopted control records an immutable population by run ID. Preserve
        # that exact historical population even when it contains successful
        # reductions from an earlier solver version.
        all_rows = connection.execute(
            f"SELECT {columns} FROM runs ORDER BY recorded_at_utc,run_id"
        ).fetchall()
    audit: list[AuditRow] = []
    if run_ids is not None:
        by_id = {str(row[0]): row for row in all_rows}
        missing = sorted(run_ids - by_id.keys())
        if missing:
            raise ValueError(f"requested run IDs unavailable: {','.join(missing)}")
        selected = [by_id[run_id] for run_id in sorted(run_ids)]
        for row in selected:
            if int(row[5]) != 0:
                raise ValueError(f"requested run is not successful: {row[0]}")
    else:
        latest: dict[str, tuple[object, ...]] = {}
        for row in all_rows:
            run_id, _, _, raw_source_sha256, _, exit_code, _, raw_catalogue = row
            source_sha256 = str(raw_source_sha256 or "")
            if int(exit_code) != 0:
                audit.append(_audit("run", str(run_id), source_sha256, reasons=("failed_run",)))
                continue
            if source_sha256 not in observations:
                audit.append(
                    _audit("run", str(run_id), source_sha256, reasons=("missing_manifest_hash",))
                )
                continue
            if not raw_catalogue:
                audit.append(
                    _audit("run", str(run_id), source_sha256, reasons=("missing_catalogue_sha256",))
                )
                continue
            previous = latest.get(source_sha256)
            if previous is not None:
                audit.append(
                    _audit(
                        "run",
                        str(previous[0]),
                        source_sha256,
                        reasons=("superseded_successful_run",),
                    )
                )
            latest[source_sha256] = row
        selected = sorted(latest.values(), key=lambda row: str(row[0]))

    seen_sources: set[str] = set()
    for row in selected:
        source_sha256 = str(row[3] or "")
        if not source_sha256 or source_sha256 not in observations:
            raise ValueError(f"selected run lacks manifest observation: {row[0]}")
        if not row[7]:
            raise ValueError(f"selected run lacks catalogue hash: {row[0]}")
        if source_sha256 in seen_sources:
            raise ValueError(f"selected runs duplicate source hash: {source_sha256}")
        seen_sources.add(source_sha256)
    return selected, audit


def load_measurements(
    database: Path,
    manifest: Path,
    *,
    input_solver_version: str = "0.21.0",
    run_ids: frozenset[str] | None = None,
) -> MeasurementSet:
    """Load one immutable measurement population without modifying its inputs."""

    database = Path(database)
    manifest = Path(manifest)
    database_sha256 = _sha256(database)
    manifest_sha256 = _sha256(manifest)
    with _read_only(manifest) as connection:
        observations = {
            str(source_sha256): (str(midpoint), float(exposure))
            for source_sha256, midpoint, exposure in connection.execute(
                "SELECT source_sha256,header_midpoint_utc,exposure_seconds FROM mmto_v21_observations"
            )
        }

    run_records: list[RunRecord] = []
    stellar: list[StellarMeasurement] = []
    planets: list[PlanetMeasurement] = []
    audit: list[AuditRow] = []
    colour_cache: dict[str, Mapping[str, tuple[float | None, float | None]]] = {}

    with _read_only(database) as connection:
        connection.execute("BEGIN")
        selected, selection_audit = _select_runs(
            connection,
            observations,
            input_solver_version=input_solver_version,
            run_ids=run_ids,
        )
        audit.extend(selection_audit)
        for row in selected:
            (
                raw_run_id,
                recorded_at_utc,
                source_path,
                raw_source_sha256,
                analysis_path,
                _,
                solver_version,
                raw_catalogue_sha256,
            ) = row
            run_id = str(raw_run_id)
            source_sha256 = str(raw_source_sha256)
            catalogue_sha256 = str(raw_catalogue_sha256)
            observed_utc, manifest_exposure = observations[source_sha256]
            product = connection.execute(
                "SELECT content FROM products WHERE run_id=? AND product='dots/detection.json'",
                (run_id,),
            ).fetchall()
            if len(product) != 1:
                raise ValueError(f"missing or non-unique dots/detection.json: {run_id}")
            detection = _json_object(product[0][0], label=f"{run_id}:dots/detection.json")
            width = _integer(detection.get("width_px"))
            height = _integer(detection.get("height_px"))
            if width is None or height is None or width <= 0 or height <= 0:
                raise ValueError(f"invalid image dimensions in dots/detection.json: {run_id}")
            input_image = detection.get("input_image")
            exposure = None
            if isinstance(input_image, dict) and isinstance(input_image.get("exposure"), dict):
                exposure = _positive(input_image["exposure"].get("seconds"))
            if exposure is None:
                exposure = _positive(manifest_exposure)
            global_noise = _finite(detection.get("global_noise_adu"))
            run_record = RunRecord(
                run_id=run_id,
                recorded_at_utc=str(recorded_at_utc),
                source_path=str(source_path),
                source_sha256=source_sha256,
                analysis_path=str(analysis_path),
                solver_version=str(solver_version),
                catalogue_sha256=catalogue_sha256,
                observed_utc=observed_utc,
                night=_night(observed_utc),
                width_px=width,
                height_px=height,
                global_noise_adu=global_noise,
                exposure_seconds=exposure,
            )
            run_records.append(run_record)

            source_rows = _unique_by_detection(
                _measurement_rows(connection, run_id, "source_photometry.csv"),
                "source_photometry.csv",
            )
            coordinate_rows = _unique_coordinates(
                _measurement_rows(connection, run_id, "star_coordinates.csv")
            )
            candidate_rows = _unique_by_detection(
                _measurement_rows(connection, run_id, "dots/star_candidates.csv"),
                "dots/star_candidates.csv",
            )
            if catalogue_sha256 not in colour_cache:
                colour_cache[catalogue_sha256] = _catalogue_colours(catalogue_sha256)
            colours = colour_cache[catalogue_sha256]

            seen_stars: set[tuple[str, str]] = set()
            for _, raw_star_id, raw_detection_id, values in _measurement_rows(
                connection, run_id, "stellar_photometry.csv"
            ):
                star_id = raw_star_id or str(values.get("star_id", ""))
                detection_id = raw_detection_id or str(values.get("detection_id", ""))
                key = (star_id, detection_id)
                if not all(key) or key in seen_stars:
                    raise ValueError(f"non-unique stellar measurement join: {run_id}:{key}")
                seen_stars.add(key)
                try:
                    source = source_rows[detection_id]
                    coordinate = coordinate_rows[key]
                    candidate = candidate_rows[detection_id]
                except KeyError as error:
                    raise ValueError(
                        f"missing detection join for stellar row {run_id}:{star_id}:{detection_id}"
                    ) from error
                x = _finite(coordinate.get("x_px"))
                y = _finite(coordinate.get("y_px"))
                magnitude = _finite(values.get("catalogue_magnitude"))
                airmass = _positive(values.get("airmass"))
                saturation_known = _boolean(values.get("saturation_known"))
                bp, rp = colours.get(star_id, (None, None))
                colour = bp - rp if bp is not None and rp is not None else None
                for channel in CHANNELS:
                    reasons: list[str] = []
                    rate = _positive(values.get(f"{channel}_count_rate_adu_per_s"))
                    saturated = _boolean(values.get(f"{channel}_saturated"))
                    method = str(values.get(f"{channel}_measurement_method", ""))
                    if magnitude is None:
                        reasons.append("invalid_catalogue_magnitude")
                    if airmass is None:
                        reasons.append("invalid_airmass")
                    if x is None or y is None:
                        reasons.append("invalid_position")
                    if rate is None:
                        reasons.append("invalid_count_rate")
                    if saturation_known is not True or saturated is None:
                        reasons.append("saturation_unknown")
                    elif saturated:
                        reasons.append("channel_saturated")
                    if method != "aperture":
                        reasons.append("not_ordinary_aperture")
                    audit.append(
                        _audit(
                            "stellar",
                            run_id,
                            source_sha256,
                            star_id=star_id,
                            detection_id=detection_id,
                            channel=channel,
                            reasons=reasons,
                        )
                    )
                    if reasons:
                        continue
                    assert None not in (magnitude, airmass, x, y, rate)
                    background = _finite(
                        source.get(f"{channel}_aperture_background_adu")
                    )
                    stellar.append(
                        StellarMeasurement(
                            run_id=run_id,
                            source_sha256=source_sha256,
                            observed_utc=observed_utc,
                            night=run_record.night,
                            catalogue_sha256=catalogue_sha256,
                            star_id=star_id,
                            detection_id=detection_id,
                            channel=channel,
                            catalogue_magnitude=float(magnitude),
                            count_rate_adu_per_s=float(rate),
                            machine_magnitude=-2.5 * math.log10(float(rate)),
                            airmass=float(airmass),
                            x_px=float(x),
                            y_px=float(y),
                            image_width_px=width,
                            image_height_px=height,
                            source_class=str(source.get("source_class", values.get("source_class", ""))),
                            exposure_seconds=_positive(source.get("exposure_seconds")) or exposure,
                            flux_adu=_finite(values.get(f"{channel}_flux")),
                            saturation_known=True,
                            saturated=False,
                            measurement_method="ordinary_aperture",
                            area_px=_finite(candidate.get("area_px")),
                            major_sigma_px=_finite(candidate.get("major_sigma_px")),
                            axis_ratio=_finite(candidate.get("axis_ratio")),
                            peak_snr=_finite(candidate.get("peak_snr")),
                            aperture_radius_px=_aperture_radius(candidate),
                            aperture_background_adu=background,
                            global_noise_adu=global_noise,
                            gaia_bp_magnitude=bp,
                            gaia_rp_magnitude=rp,
                            gaia_bp_minus_rp=colour,
                        )
                    )

            for _, _, raw_detection_id, values in _measurement_rows(
                connection, run_id, "identified_source_photometry.csv"
            ):
                identity_type = str(values.get("identity_type", ""))
                if identity_type not in {"major_planet", "minor_planet"}:
                    continue
                identity_name = str(values.get("identity_name", ""))
                detection_id = raw_detection_id or str(values.get("detection_id", ""))
                try:
                    source = source_rows[detection_id]
                    candidate = candidate_rows[detection_id]
                except KeyError as error:
                    raise ValueError(
                        f"missing detection join for planet row {run_id}:{identity_name}:{detection_id}"
                    ) from error
                x = _finite(values.get("x_px"))
                y = _finite(values.get("y_px"))
                saturation_known = _boolean(values.get("saturation_known"))
                for channel in CHANNELS:
                    reasons = []
                    rate = _positive(values.get(f"{channel}_count_rate_adu_per_s"))
                    saturated = _boolean(values.get(f"{channel}_saturated"))
                    method = str(values.get(f"{channel}_measurement_method", ""))
                    if not identity_name:
                        reasons.append("missing_planet_identity")
                    if x is None or y is None:
                        reasons.append("invalid_position")
                    if rate is None:
                        reasons.append("invalid_count_rate")
                    if saturation_known is not True or saturated is None:
                        reasons.append("saturation_unknown")
                    elif saturated:
                        reasons.append("channel_saturated")
                    if method != "aperture":
                        reasons.append("not_ordinary_aperture")
                    reason_tuple = tuple(dict.fromkeys(reasons))
                    audit.append(
                        _audit(
                            "planet",
                            run_id,
                            source_sha256,
                            detection_id=detection_id,
                            identity_name=identity_name,
                            channel=channel,
                            reasons=reason_tuple,
                        )
                    )
                    planets.append(
                        PlanetMeasurement(
                            run_id=run_id,
                            source_sha256=source_sha256,
                            observed_utc=observed_utc,
                            night=run_record.night,
                            identity_type=identity_type,
                            identity_name=identity_name,
                            identity_status=str(values.get("identity_status", "")),
                            candidate_rank=_integer(values.get("candidate_rank")),
                            epoch_tdb=(str(values["epoch_tdb"]) if values.get("epoch_tdb") else None),
                            detection_id=detection_id,
                            channel=channel,
                            count_rate_adu_per_s=rate,
                            machine_magnitude=(-2.5 * math.log10(rate) if rate is not None else None),
                            x_px=x,
                            y_px=y,
                            image_width_px=width,
                            image_height_px=height,
                            source_class=str(source.get("source_class", values.get("source_class", ""))),
                            exposure_seconds=_positive(source.get("exposure_seconds")) or exposure,
                            flux_adu=_finite(values.get(f"{channel}_flux")),
                            saturation_known=saturation_known,
                            saturated=saturated,
                            measurement_method=("ordinary_aperture" if method == "aperture" else method),
                            area_px=_finite(candidate.get("area_px")),
                            major_sigma_px=_finite(candidate.get("major_sigma_px")),
                            axis_ratio=_finite(candidate.get("axis_ratio")),
                            peak_snr=_finite(candidate.get("peak_snr")),
                            aperture_radius_px=_aperture_radius(candidate),
                            aperture_background_adu=_finite(
                                source.get(f"{channel}_aperture_background_adu")
                            ),
                            global_noise_adu=global_noise,
                            valid_measurement=not reason_tuple,
                            exclusion_reasons=reason_tuple,
                        )
                    )

    run_records.sort(key=lambda item: item.run_id)
    stellar.sort(
        key=lambda item: (
            item.observed_utc,
            item.catalogue_sha256,
            item.star_id,
            item.channel,
        )
    )
    planets.sort(
        key=lambda item: (
            item.observed_utc,
            item.identity_type,
            item.identity_name,
            item.detection_id,
            item.channel,
        )
    )
    audit.sort(
        key=lambda item: (
            item.row_type,
            item.run_id,
            item.star_id,
            item.identity_name,
            item.detection_id,
            item.channel,
            item.exclusion_reasons,
        )
    )
    return MeasurementSet(
        runs=tuple(run_records),
        stellar=tuple(stellar),
        planets=tuple(planets),
        audit=tuple(audit),
        database_path=str(database.resolve()),
        manifest_path=str(manifest.resolve()),
        database_sha256=database_sha256,
        manifest_sha256=manifest_sha256,
        input_solver_version=input_solver_version,
    )


def load_v21_control(directory: Path) -> V21Control:
    directory = Path(directory)
    manifest_path = directory / "calibration_manifest.json"
    corrected_path = directory / "corrected_stellar_photometry.csv"
    coefficients_path = directory / "nightly_extinction_coefficients.csv"
    manifest = _json_object(manifest_path.read_bytes(), label=str(manifest_path))
    adopted = str(manifest.get("adopted_model", ""))
    raw_run_ids = manifest.get("selected_run_ids")
    if not adopted or not isinstance(raw_run_ids, list) or not raw_run_ids:
        raise ValueError("invalid v21 calibration manifest")
    selected = frozenset(str(value) for value in raw_run_ids)
    if len(selected) != len(raw_run_ids):
        raise ValueError("duplicate selected run IDs in v21 control")

    corrected: dict[tuple[str, str, str, str], float] = {}
    with corrected_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            value = _finite(row.get("corrected_magnitude"))
            if value is None or str(row.get("status", "")) != "accepted":
                continue
            key = (
                str(row.get("source_sha256", "")),
                str(row.get("catalogue_sha256", "")),
                str(row.get("star_id", "")),
                str(row.get("channel", "")),
            )
            if not all(key):
                raise ValueError("invalid corrected stellar control key")
            if key in corrected:
                raise ValueError(f"duplicate corrected stellar control row: {key}")
            corrected[key] = value

    coefficients: dict[tuple[str, str, str], float] = {}
    with coefficients_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if str(row.get("model", "")) != adopted or str(row.get("status", "")) != "accepted":
                continue
            value = _finite(row.get("extinction_mag_per_airmass"))
            if value is None:
                continue
            key = (
                str(row.get("night", "")),
                str(row.get("channel", "")),
                str(row.get("catalogue_sha256", "")),
            )
            if not all(key):
                raise ValueError("invalid v21 extinction coefficient key")
            if key in coefficients:
                raise ValueError(f"duplicate v21 extinction coefficient: {key}")
            coefficients[key] = value

    return V21Control(
        selected_run_ids=selected,
        adopted_model=adopted,
        corrected_magnitudes=MappingProxyType(corrected),
        extinction_coefficients=MappingProxyType(coefficients),
        manifest_sha256=_sha256(manifest_path),
        corrected_photometry_sha256=_sha256(corrected_path),
        coefficients_sha256=_sha256(coefficients_path),
    )


def require_matching_runs(control: V21Control, data: MeasurementSet) -> None:
    measured = frozenset(run.run_id for run in data.runs)
    if control.selected_run_ids != measured:
        missing = sorted(control.selected_run_ids - measured)
        extra = sorted(measured - control.selected_run_ids)
        raise ValueError(f"control run mismatch: missing={missing}; extra={extra}")


def write_input_audit(data: MeasurementSet, output: Path) -> None:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with (output / "input_runs.csv").open("w", newline="", encoding="utf-8") as stream:
        fields = (
            "run_id",
            "recorded_at_utc",
            "observed_utc",
            "night",
            "source_path",
            "source_sha256",
            "catalogue_sha256",
            "solver_version",
            "database_sha256",
            "manifest_sha256",
        )
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for run in data.runs:
            writer.writerow(
                {
                    "run_id": run.run_id,
                    "recorded_at_utc": run.recorded_at_utc,
                    "observed_utc": run.observed_utc,
                    "night": run.night,
                    "source_path": run.source_path,
                    "source_sha256": run.source_sha256,
                    "catalogue_sha256": run.catalogue_sha256,
                    "solver_version": run.solver_version,
                    "database_sha256": data.database_sha256,
                    "manifest_sha256": data.manifest_sha256,
                }
            )
    with (output / "measurement_audit.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        fields = (
            "row_type",
            "run_id",
            "source_sha256",
            "star_id",
            "detection_id",
            "identity_name",
            "channel",
            "included",
            "exclusion_reasons",
        )
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in data.audit:
            writer.writerow(
                {
                    "row_type": row.row_type,
                    "run_id": row.run_id,
                    "source_sha256": row.source_sha256,
                    "star_id": row.star_id,
                    "detection_id": row.detection_id,
                    "identity_name": row.identity_name,
                    "channel": row.channel,
                    "included": str(row.included).lower(),
                    "exclusion_reasons": ";".join(row.exclusion_reasons),
                }
            )
