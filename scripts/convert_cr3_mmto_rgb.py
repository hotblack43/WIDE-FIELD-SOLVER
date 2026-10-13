#!/usr/bin/env python3
"""Convert camera RAW files to MMTO-like linear three-plane RGB FITS cubes."""

from __future__ import annotations

import argparse
import bz2
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from astropy.io import fits
import numpy as np


PEDESTAL = 1870
POSITIVE_INT16_MAX = 32767


def normalise_metadata(record: dict[str, object]) -> dict[str, object]:
    """Translate ExifTool JSON names and preserve timezone provenance."""
    metadata = {
        "make": record.get("Make"),
        "model": record.get("Model"),
        "exposure": (None if record.get("ExposureTime") is None
                     else float(record["ExposureTime"])),
        "iso": None if record.get("ISO") is None else int(record["ISO"]),
        "f_number": (None if record.get("FNumber") is None
                     else float(record["FNumber"])),
        "focal_length": (None if record.get("FocalLength") is None
                         else float(record["FocalLength"])),
        "date_original": record.get("DateTimeOriginal"),
        "subsec_original": (None if record.get("SubSecTimeOriginal") is None
                            else str(record["SubSecTimeOriginal"])),
        "offset_original": record.get("OffsetTimeOriginal"),
        "lens_model": record.get("LensModel"),
        "lens_info": record.get("LensInfo"),
        "focus_mode": record.get("FocusMode"),
        "focus_range": record.get("FocusRange"),
        "hyperfocal_distance": record.get("HyperfocalDistance"),
        "circle_of_confusion": record.get("CircleOfConfusion"),
        "af_area_mode": record.get("AFAreaMode"),
        "white_balance": record.get("WhiteBalance"),
        "colour_temperature": record.get("ColorTemperature"),
        "camera_temperature": record.get("CameraTemperature"),
        "exposure_mode": record.get("ExposureMode"),
        "exposure_program": record.get("ExposureProgram"),
        "metering_mode": record.get("MeteringMode"),
        "image_stabilization": record.get("ImageStabilization"),
        "long_exposure_noise_reduction": record.get("LongExposureNoiseReduction"),
        "high_iso_noise_reduction": record.get("HighISONoiseReduction"),
        "orientation": record.get("Orientation"),
    }
    date = metadata["date_original"]
    offset = metadata["offset_original"]
    if date and offset:
        subsecond = str(metadata["subsec_original"] or "").strip()
        stamp = f"{date}.{subsecond}{offset}" if subsecond else f"{date}{offset}"
        pattern = "%Y:%m:%d %H:%M:%S.%f%z" if subsecond else "%Y:%m:%d %H:%M:%S%z"
        local = datetime.strptime(stamp, pattern)
        metadata["date_obs"] = local.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )
    else:
        metadata["date_obs"] = None
    return metadata


def mmto_cube(rgb: np.ndarray, *, pedestal: int = PEDESTAL) -> np.ndarray:
    """Map linear uint16 RGB to MMTO's positive signed-int16 convention."""
    values = np.asarray(rgb)
    if values.ndim != 3 or values.shape[-1] != 3:
        raise ValueError(f"Expected height x width x 3 RGB, got {values.shape}")
    if values.dtype != np.uint16:
        raise ValueError(f"Expected uint16 linear RGB, got {values.dtype}")
    if not 0 <= pedestal < POSITIVE_INT16_MAX:
        raise ValueError("Pedestal must be between 0 and 32766 ADU")
    scale = (POSITIVE_INT16_MAX - pedestal) / np.iinfo(np.uint16).max
    mapped = np.rint(pedestal + values.astype(np.float64) * scale)
    mapped = np.clip(mapped, 0, POSITIVE_INT16_MAX).astype(np.int16)
    return np.moveaxis(mapped, -1, 0)


def _ppm_token(handle) -> bytes:
    while True:
        byte = handle.read(1)
        if not byte:
            raise ValueError("Unexpected end of PPM header")
        if byte == b"#":
            handle.readline()
            continue
        if not byte.isspace():
            break
    token = bytearray(byte)
    while True:
        byte = handle.read(1)
        if not byte or byte.isspace():
            return bytes(token)
        token.extend(byte)


def read_ppm16(path: Path) -> np.ndarray:
    """Read a binary 16-bit RGB PPM without Pillow's eight-bit conversion."""
    with Path(path).open("rb") as handle:
        magic = _ppm_token(handle)
        width = int(_ppm_token(handle))
        height = int(_ppm_token(handle))
        maximum = int(_ppm_token(handle))
        if magic != b"P6" or maximum != 65535:
            raise ValueError(
                f"Expected 16-bit binary PPM (P6, max 65535), got {magic!r}, max {maximum}"
            )
        payload = handle.read()
    expected = height * width * 3 * 2
    if len(payload) != expected:
        raise ValueError(f"PPM payload has {len(payload)} bytes; expected {expected}")
    return np.frombuffer(payload, dtype=">u2").reshape(height, width, 3).astype(np.uint16)


def write_mmto_fits(
    source: Path,
    target: Path,
    rgb: np.ndarray,
    metadata: dict[str, object],
    *,
    pedestal: int = PEDESTAL,
) -> Path:
    """Write one verified, linear RGB, MMTO-layout FITS file."""
    source = Path(source).resolve()
    target = Path(target).resolve()
    cube = mmto_cube(rgb, pedestal=pedestal)
    header = fits.Header()
    header["DATE"] = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    header["SWCREATE"] = "WIDE-FIELD-SOLVER LibRaw RGB converter"
    header["ORIGIN"] = "KNALDGAS"
    header["CHANNELS"] = "R,G,B"
    header["PLANE1"] = "R"
    header["PLANE2"] = "G"
    header["PLANE3"] = "B"
    header["BUNIT"] = "adu"
    header["BITCAMPX"] = 15
    header["PEDESTAL"] = pedestal
    header["COLSPACE"] = "LINEAR_SRGB"
    header["TRANSFER"] = "LINEAR"
    header["GAMMA"] = 1.0
    header["PHOTLINE"] = True
    header["DEMOSAIC"] = "LIBRAW_HALF"
    header["DATAMIN"] = int(cube.min())
    header["DATAMAX"] = int(cube.max())
    header["SRCFILE"] = source.name
    header["SRCSHA"] = hashlib.sha256(source.read_bytes()).hexdigest()
    if metadata.get("model"):
        header["INSTRUME"] = str(metadata["model"])
    if metadata.get("make"):
        header["CAMMAKE"] = str(metadata["make"])
    if metadata.get("exposure") is not None:
        header["EXPOSURE"] = float(metadata["exposure"])
        header["EXPTIME"] = (float(metadata["exposure"]), "Exposure time, seconds")
    if metadata.get("iso") is not None:
        header["ISOSPEED"] = int(metadata["iso"])
    if metadata.get("f_number") is not None:
        header["APERTURE"] = float(metadata["f_number"])
    if metadata.get("focal_length") is not None:
        header["FOCAL"] = float(metadata["focal_length"])
        header["FOCALLEN"] = (float(metadata["focal_length"]), "Lens focal length, mm")
    if metadata.get("date_original"):
        header["DATEORIG"] = str(metadata["date_original"])
    if metadata.get("offset_original"):
        header["UTCOFFST"] = str(metadata["offset_original"])
    if metadata.get("subsec_original"):
        header["SUBSEC"] = str(metadata["subsec_original"])
    if metadata.get("date_obs"):
        header["DATE-OBS"] = str(metadata["date_obs"])
    optional_cards = (
        ("LENSMOD", "lens_model", "Lens model"),
        ("LENSINFO", "lens_info", "ExifTool LensInfo"),
        ("FOCUSMOD", "focus_mode", "ExifTool numeric focus mode"),
        ("FOCUSRNG", "focus_range", "ExifTool numeric focus range"),
        ("HYPERFOC", "hyperfocal_distance", "ExifTool hyperfocal distance, m"),
        ("CIRCCONF", "circle_of_confusion", "ExifTool circle of confusion, mm"),
        ("AFAREAMD", "af_area_mode", "ExifTool numeric AF area mode"),
        ("WHITEBAL", "white_balance", "ExifTool numeric white balance mode"),
        ("COLORTMP", "colour_temperature", "Colour temperature, K"),
        ("CAMTEMP", "camera_temperature", "Camera temperature, deg C"),
        ("EXPMODE", "exposure_mode", "ExifTool numeric exposure mode"),
        ("EXPPROG", "exposure_program", "ExifTool numeric exposure program"),
        ("METERING", "metering_mode", "ExifTool numeric metering mode"),
        ("IMGSTAB", "image_stabilization", "ExifTool numeric image stabilization"),
        ("LENR", "long_exposure_noise_reduction", "Long-exposure noise reduction"),
        ("HINR", "high_iso_noise_reduction", "High-ISO noise reduction"),
        ("ORIENTAT", "orientation", "ExifTool numeric orientation"),
    )
    for keyword, field, comment in optional_cards:
        value = metadata.get(field)
        if value not in (None, ""):
            header[keyword] = (value, comment)
    header.add_history("LibRaw half-size demosaic with camera white balance and colour matrix.")
    header.add_history("Linear sRGB; one common affine scale preserves inter-channel ratios.")
    header.add_history("Positive 15-bit signed-integer convention follows MMTO colour FITS.")

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    fits.PrimaryHDU(cube, header=header).writeto(partial, checksum=True)
    os.replace(partial, target)
    with fits.open(target, checksum=True, memmap=False) as hdus:
        if hdus[0].data.shape != cube.shape or hdus[0].data.dtype.kind != "i":
            raise RuntimeError(f"FITS verification failed for {target}")
        if hdus[0].verify_checksum() != 1 or hdus[0].verify_datasum() != 1:
            raise RuntimeError(f"FITS checksum verification failed for {target}")
        if not np.array_equal(hdus[0].data, cube):
            raise RuntimeError(f"FITS pixels differ from converted RGB for {target}")
    return target


def compress_verified_fits(plain: Path, target: Path) -> Path:
    """Atomically create a verified bzip2 FITS and remove the plain input."""
    plain = Path(plain).resolve()
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    with plain.open("rb") as source, bz2.open(partial, "wb", compresslevel=9) as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)
    with bz2.open(partial, "rb") as compressed:
        with fits.open(compressed, checksum=True, memmap=False) as hdus:
            if hdus[0].verify_checksum() != 1 or hdus[0].verify_datasum() != 1:
                raise RuntimeError(f"Compressed FITS checksum verification failed for {target}")
    os.replace(partial, target)
    plain.unlink()
    return target


def discover_raw_files(root: Path) -> list[Path]:
    root = Path(root).resolve()
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".cr2", ".cr3"}
    )


def output_path(source: Path, root: Path, output: Path) -> Path:
    relative = Path(source).resolve().relative_to(Path(root).resolve())
    return Path(output).resolve() / relative.parent / f"{relative.stem}_RGB.fits.bz2"


def filter_by_exposure(
    records: list[tuple[Path, dict[str, object]]],
    *,
    minimum: float,
) -> tuple[list[tuple[Path, dict[str, object]]], list[tuple[Path, dict[str, object]]]]:
    """Split metadata records at an inclusive minimum exposure time."""
    selected = []
    excluded = []
    for record in records:
        exposure = record[1].get("exposure")
        destination = selected if exposure is not None and float(exposure) >= minimum else excluded
        destination.append(record)
    return selected, excluded


def extract_metadata(source: Path) -> dict[str, object]:
    command = [
        "exiftool", "-j", "-n", "-Make", "-Model", "-ExposureTime", "-ISO",
        "-FNumber", "-FocalLength", "-DateTimeOriginal", "-SubSecTimeOriginal",
        "-OffsetTimeOriginal", "-LensModel", "-LensInfo", "-FocusMode",
        "-FocusRange", "-HyperfocalDistance", "-CircleOfConfusion", "-AFAreaMode",
        "-WhiteBalance", "-ColorTemperature", "-CameraTemperature", "-ExposureMode",
        "-ExposureProgram", "-MeteringMode", "-ImageStabilization",
        "-LongExposureNoiseReduction", "-HighISONoiseReduction", "-Orientation",
        str(Path(source).resolve()),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    records = json.loads(completed.stdout)
    if len(records) != 1:
        raise RuntimeError(f"ExifTool returned {len(records)} records for {source}")
    return normalise_metadata(records[0])


def develop_linear_rgb(source: Path, temporary_directory: Path) -> np.ndarray:
    """Use LibRaw to create half-resolution, white-balanced linear sRGB."""
    ppm = Path(temporary_directory) / "linear_rgb.ppm"
    command = [
        "/usr/bin/dcraw_emu", "-w", "+M", "-o", "1", "-H", "0", "-h", "-4",
        "-Z", str(ppm), str(Path(source).resolve()),
    ]
    subprocess.run(command, check=True)
    if not ppm.is_file():
        raise RuntimeError(f"LibRaw did not create {ppm}")
    return read_ppm16(ppm)


def convert_one(
    source: Path,
    target: Path,
    *,
    overwrite: bool = False,
    pedestal: int = PEDESTAL,
    min_exposure: float | None = None,
) -> str:
    source = Path(source).resolve()
    target = Path(target).resolve()
    metadata = extract_metadata(source)
    if min_exposure is not None:
        selected, _ = filter_by_exposure([(source, metadata)], minimum=min_exposure)
        if not selected:
            return "excluded"
    if target.exists() and not overwrite:
        return "skipped"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="knaldgas-rgb-", dir=target.parent) as directory:
        temporary = Path(directory)
        rgb = develop_linear_rgb(source, temporary)
        plain = temporary / target.name.removesuffix(".bz2")
        write_mmto_fits(source, plain, rgb, metadata, pedestal=pedestal)
        compress_verified_fits(plain, target)
    return "written"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Canon RAW files to MMTO-like linear RGB FITS cubes."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", action="append", type=Path,
                        help="Convert only this source; may be repeated")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--pedestal", type=int, default=PEDESTAL)
    parser.add_argument(
        "--min-exposure", type=float,
        help="Convert only frames at least this many seconds long (inclusive)",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    output = args.output.resolve()
    sources = ([path.resolve() for path in args.source]
               if args.source else discover_raw_files(root))
    for source in sources:
        source.relative_to(root)
        if source.suffix.lower() not in {".cr2", ".cr3"} or not source.is_file():
            parser.error(f"Not a readable CR2/CR3 source: {source}")
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        sources = sources[:args.limit]
    if args.min_exposure is not None and args.min_exposure < 0:
        parser.error("--min-exposure must not be negative")
    if not sources:
        parser.error(f"No CR2/CR3 files found under {root}")

    counts = {"written": 0, "skipped": 0, "excluded": 0, "failed": 0}
    for number, source in enumerate(sources, start=1):
        target = output_path(source, root, output)
        try:
            state = convert_one(
                source, target, overwrite=args.overwrite, pedestal=args.pedestal,
                min_exposure=args.min_exposure,
            )
            counts[state] += 1
            print(f"[{number}/{len(sources)}] {state}: {target}", flush=True)
        except Exception as error:
            counts["failed"] += 1
            print(f"[{number}/{len(sources)}] FAILED: {source}: {error}", flush=True)
    print(
        f"SUMMARY total={len(sources)} written={counts['written']} "
        f"skipped={counts['skipped']} excluded={counts['excluded']} "
        f"failed={counts['failed']}",
        flush=True,
    )
    return 0 if counts["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

