from __future__ import annotations

import bz2
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterator

from astropy.io import fits
import numpy as np
from PIL import Image


UTC = timezone.utc
PERCENTILES = (1, 5, 50, 95, 99, 99.9)


def _number(value: np.generic | int | float) -> int | float:
    value = value.item() if isinstance(value, np.generic) else value
    if isinstance(value, (int, np.integer)):
        return int(value)
    return float(value)


def array_statistics(
    array: np.ndarray, saturation_level: int | float | None = None
) -> dict[str, object]:
    values = np.asarray(array)
    flat = values.reshape(-1)
    if np.issubdtype(flat.dtype, np.number):
        finite = flat[np.isfinite(flat)]
    else:
        finite = np.array([], dtype=np.float64)
    record: dict[str, object] = {
        "dtype": str(values.dtype),
        "shape": list(values.shape),
        "element_count": int(values.size),
        "finite_count": int(finite.size),
    }
    if not finite.size:
        return record
    minimum = _number(np.min(finite))
    maximum = _number(np.max(finite))
    record.update(
        minimum=minimum,
        maximum=maximum,
        median=_number(np.median(finite)),
        percentiles={
            str(level): _number(value)
            for level, value in zip(PERCENTILES, np.percentile(finite, PERCENTILES))
        },
    )
    span = float(maximum) - float(minimum) + 1
    record["occupied_bits"] = int(math.ceil(math.log2(span))) if span > 1 else 0
    if np.issubdtype(finite.dtype, np.integer) and span <= 1_000_000:
        distinct = np.unique(finite)
        record["distinct_values"] = int(distinct.size)
        record["distinct_values_exact"] = True
    else:
        count = min(int(finite.size), 1_000_000)
        indices = np.linspace(0, finite.size - 1, count, dtype=np.int64)
        record["distinct_values"] = int(np.unique(finite[indices]).size)
        record["distinct_values_exact"] = count == finite.size
    if saturation_level is not None:
        record["saturation_level"] = _number(saturation_level)
        record["saturation_fraction"] = float(np.count_nonzero(finite >= saturation_level) / finite.size)
    return record


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


@contextmanager
def _fits_source(path: Path) -> Iterator[str | io.BytesIO]:
    if path.name.lower().endswith(".bz2"):
        with bz2.open(path, "rb") as stream:
            yield io.BytesIO(stream.read())
    else:
        yield str(path)


def _fits_metadata(header: fits.Header) -> dict[str, object]:
    keys = (
        "DATE-OBS", "DATE", "EXPTIME", "EXPOSURE", "INSTRUME", "TELESCOP",
        "ORIGIN", "SITELAT", "SITELONG", "BAYERPAT", "BAYERIND", "BITCAMPX",
        "GAIN", "GAIN_ELE", "OFFSET", "OFFSET_E", "CCD-TEMP", "DATAMIN", "DATAMAX",
    )
    return {key: _json_value(header[key]) for key in keys if key in header}


def _fits_saturation_level(header: fits.Header) -> int | float | None:
    camera_bits = header.get("BITCAMPX")
    if isinstance(camera_bits, (int, np.integer)) and 1 <= int(camera_bits) <= 64:
        return (1 << int(camera_bits)) - 1
    return None


def inspect_fits(path: Path) -> dict[str, object]:
    path = Path(path)
    entries: list[dict[str, object]] = []
    with _fits_source(path) as source:
        with fits.open(source, memmap=False, uint=True) as hdus:
            for index, hdu in enumerate(hdus):
                header = hdu.header
                data = hdu.data
                entry: dict[str, object] = {
                    "index": index,
                    "name": hdu.name or "PRIMARY",
                    "class": type(hdu).__name__,
                    "bitpix": int(header.get("BITPIX", 0)),
                    "bscale": _json_value(header.get("BSCALE", 1)),
                    "bzero": _json_value(header.get("BZERO", 0)),
                    "header": _fits_metadata(header),
                }
                if data is not None:
                    saturation = _fits_saturation_level(header)
                    entry["statistics"] = array_statistics(data, saturation)
                entries.append(entry)
    return {"format": "fits", "path": str(path), "compression": "bz2" if path.name.lower().endswith(".bz2") else None, "hdus": entries}


def inspect_hdf5(path: Path) -> dict[str, object]:
    try:
        import h5py
    except ImportError as exc:
        raise RuntimeError("HDF5 inspection requires h5py; run inspect_allsky_samples.py with uv --script") from exc

    objects: list[dict[str, object]] = []
    with h5py.File(path, "r") as handle:
        root_attrs = {str(key): _json_value(value) for key, value in handle.attrs.items()}

        def visit(name: str, obj: Any) -> None:
            item: dict[str, object] = {
                "path": "/" + name,
                "kind": "dataset" if isinstance(obj, h5py.Dataset) else "group",
                "attributes": {str(key): _json_value(value) for key, value in obj.attrs.items()},
            }
            if isinstance(obj, h5py.Dataset):
                item["shape"] = list(obj.shape)
                item["dtype"] = str(obj.dtype)
                if np.issubdtype(obj.dtype, np.number) and obj.size:
                    item["statistics"] = array_statistics(obj[...])
            objects.append(item)

        handle.visititems(visit)
    return {"format": "hdf5", "path": str(path), "root_attributes": root_attrs, "objects": objects}


def _bayer_pattern(raw: Any) -> str | None:
    pattern = getattr(raw, "raw_pattern", None)
    descriptor = getattr(raw, "color_desc", None)
    if pattern is None or descriptor is None:
        return None
    descriptor = descriptor.decode("ascii", "replace") if isinstance(descriptor, bytes) else str(descriptor)
    try:
        return "".join(descriptor[int(index)] for index in np.asarray(pattern).reshape(-1))
    except (IndexError, ValueError):
        return None


def inspect_camera_raw(
    path: Path, decoder_factory: Callable[[str], Any] | None = None
) -> dict[str, object]:
    if decoder_factory is None:
        try:
            import rawpy
        except ImportError as exc:
            raise RuntimeError("camera-RAW inspection requires rawpy; run inspect_allsky_samples.py with uv --script") from exc
        decoder_factory = rawpy.imread
    with decoder_factory(str(path)) as raw:
        sensor = np.asarray(raw.raw_image_visible)
        white = getattr(raw, "white_level", None)
        other = getattr(raw, "other", None)
        sizes = getattr(raw, "sizes", None)
        raw_timestamp = getattr(other, "timestamp", None)
        metadata = {
            "iso": _json_value(getattr(other, "iso_speed", None)),
            "exposure_seconds": _json_value(getattr(other, "shutter_speed", None)),
            "aperture": _json_value(getattr(other, "aperture", None)),
            "focal_length_mm": _json_value(getattr(other, "focal_length", None)),
            "timestamp": _json_value(raw_timestamp),
        }
        if isinstance(raw_timestamp, datetime):
            observed = raw_timestamp.replace(tzinfo=UTC) if raw_timestamp.tzinfo is None else raw_timestamp.astimezone(UTC)
            metadata["timestamp_utc"] = observed.isoformat().replace("+00:00", "Z")
        elif raw_timestamp:
            metadata["timestamp_utc"] = datetime.fromtimestamp(float(raw_timestamp), UTC).isoformat().replace("+00:00", "Z")
        record = {
            "format": Path(path).suffix.lower().lstrip("/.") or "camera_raw",
            "path": str(path),
            "bayer_pattern": _bayer_pattern(raw),
            "color_descriptor": _json_value(getattr(raw, "color_desc", None)),
            "black_level_per_channel": _json_value(getattr(raw, "black_level_per_channel", None)),
            "white_level": _json_value(white),
            "camera_white_level_per_channel": _json_value(getattr(raw, "camera_white_level_per_channel", None)),
            "sizes": {
                key: _json_value(getattr(sizes, key, None))
                for key in ("raw_width", "raw_height", "width", "height")
            },
            "metadata": metadata,
            "sensor": {"statistics": array_statistics(sensor, white)},
        }
    return record


def inspect_path(path: Path) -> dict[str, object]:
    lowered = Path(path).name.lower()
    if lowered.endswith((".fits", ".fit", ".fts", ".fits.bz2", ".fit.bz2", ".fts.bz2")):
        return inspect_fits(path)
    if lowered.endswith((".h5", ".hdf5")):
        return inspect_hdf5(path)
    if lowered.endswith((".cr2", ".cr3", ".nef", ".dng", ".arw")):
        return inspect_camera_raw(path)
    raise ValueError(f"unsupported scientific image format: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _display_scale(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.float64)
    output = np.empty(rgb.shape, dtype=np.uint8)
    for channel in range(3):
        values = rgb[..., channel]
        low, high = np.percentile(values[np.isfinite(values)], (1, 99.9))
        scaled = np.clip((values - low) / max(high - low, 1), 0, 1) ** 0.45
        output[..., channel] = np.rint(scaled * 255).astype(np.uint8)
    return output


def _raw_preview(path: Path) -> np.ndarray:
    import rawpy

    with rawpy.imread(str(path)) as raw:
        mosaic = np.asarray(raw.raw_image_visible)
        pattern = _bayer_pattern(raw)
        if pattern != "RGGB":
            raise ValueError(f"preview currently requires RGGB, found {pattern!r}")
        height = mosaic.shape[0] // 2 * 2
        width = mosaic.shape[1] // 2 * 2
        data = mosaic[:height, :width].astype(np.float64)
        black = list(raw.black_level_per_channel)
        red = data[0::2, 0::2] - black[0]
        green = ((data[0::2, 1::2] - black[1]) + (data[1::2, 0::2] - black[3])) / 2
        blue = data[1::2, 1::2] - black[2]
        return np.stack((red, green, blue), axis=-1)


def _preview_pixels(path: Path, record: dict[str, object]) -> np.ndarray:
    if record["format"] in {"cr2", "cr3", "nef", "dng", "arw"}:
        return _raw_preview(path)
    if record["format"] == "hdf5":
        import h5py

        with h5py.File(path, "r") as handle:
            data = np.asarray(handle["data/images"])
        if data.ndim == 4 and data.shape[2] == 3:
            return data[..., 0]
        raise ValueError(f"unresolved HDF5 colour layout: {data.shape}")
    with _fits_source(path) as source:
        with fits.open(source, memmap=False, uint=True) as hdus:
            data = np.asarray(next(hdu.data for hdu in hdus if hdu.data is not None))
    if data.ndim == 3 and data.shape[0] == 3:
        return np.moveaxis(data, 0, -1)
    if data.ndim == 3 and data.shape[-1] == 3:
        return data
    mono = data if data.ndim == 2 else data.reshape((-1,) + data.shape[-2:])[0]
    return np.repeat(mono[..., None], 3, axis=-1)


def write_preview(path: Path, record: dict[str, object], preview_path: Path) -> Path:
    pixels = _display_scale(_preview_pixels(path, record))
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels, "RGB").save(preview_path, format="PNG", optimize=False, compress_level=9)
    return preview_path


def write_inspection(paths: list[Path], output_path: Path, preview_dir: Path | None = None) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(map(Path, paths)):
        record = inspect_path(path)
        record["size_bytes"] = path.stat().st_size
        record["sha256"] = _sha256(path)
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        record["inspection_id"] = hashlib.sha256(canonical).hexdigest()
        if preview_dir is not None:
            preview = Path(preview_dir) / (path.name + ".png")
            write_preview(path, record, preview)
            record["preview"] = str(preview)
        records.append(record)
    payload = {"schema_version": 1, "records": records}
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output_path.parent, prefix=output_path.name + ".tmp-", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, output_path)
    return records
