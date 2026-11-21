"""Native camera-RAW decoding without rendered preview substitution."""
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import exifread
import numpy as np
import rawpy


PLANE_NAMES = ('R', 'G1', 'G2', 'B')
SUPPORTED_CFA = {'RGGB', 'BGGR', 'GRBG', 'GBRG'}
_EXIF_TAGS = {
    'exposure_seconds': 'EXIF ExposureTime',
    'iso': 'EXIF ISOSpeedRatings',
    'camera_make': 'Image Make',
    'camera_model': 'Image Model',
    'lens': 'EXIF LensModel',
    'datetime_original': 'EXIF DateTimeOriginal',
    'datetime_digitized': 'EXIF DateTimeDigitized',
    'datetime': 'Image DateTime',
    'offset_time_original': 'EXIF OffsetTimeOriginal',
    'offset_time_digitized': 'EXIF OffsetTimeDigitized',
    'offset_time': 'EXIF OffsetTime',
}
_NUMERIC_EXIF_FIELDS = {'exposure_seconds', 'iso'}
_PREFIT_EXIF_FIELDS = {'exposure_seconds', 'iso', 'camera_make', 'camera_model', 'lens'}


@dataclass(frozen=True)
class CameraRawImage:
    planes: Mapping[str, np.ndarray]
    black_levels: Mapping[str, float]
    white_levels: Mapping[str, float]
    details: Mapping[str, object]


def _plain(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    model = getattr(value, 'model', None)
    return str(model if model else value)


def _numeric_tag(tag):
    values = getattr(tag, 'values', None)
    value = values[0] if isinstance(values, (tuple, list)) and values else tag
    return float(value)


def read_cr2_exif(path: Path, fields) -> dict[str, object]:
    """Return only explicitly requested normalized CR2 metadata fields."""
    requested = set(fields)
    selected = requested & set(_EXIF_TAGS)
    if not selected:
        return {}
    try:
        with Path(path).open('rb') as handle:
            tags = exifread.process_file(handle, details=False, strict=False)
    except (OSError, ValueError, TypeError):
        return {}
    answer = {}
    for field in selected:
        tag = tags.get(_EXIF_TAGS[field])
        if tag is None:
            continue
        try:
            answer[field] = _numeric_tag(tag) if field in _NUMERIC_EXIF_FIELDS else str(tag)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    return answer


def decode_cr2(path: Path) -> CameraRawImage:
    """Read visible native Bayer samples from a CR2 using LibRaw via rawpy."""
    path = Path(path)
    exif = read_cr2_exif(path, _PREFIT_EXIF_FIELDS)
    with rawpy.imread(str(path)) as raw:
        mosaic = np.asarray(raw.raw_image_visible)
        if mosaic.ndim != 2:
            raise ValueError('Camera RAW visible sensor data must be a 2-D array')
        if not np.issubdtype(mosaic.dtype, np.integer):
            raise ValueError('Camera RAW visible sensor data must contain integer samples')
        if any(size <= 0 or size % 2 for size in mosaic.shape):
            raise ValueError('Camera RAW visible sensor data must have positive even dimensions')
        pattern = np.asarray(raw.raw_pattern)
        if pattern.shape != (2, 2):
            raise ValueError('Camera RAW must describe a 2-by-2 Bayer pattern')
        description = raw.color_desc
        if isinstance(description, bytes):
            description = description.decode('ascii', errors='strict')
        try:
            letters = np.asarray([[description[int(index)] for index in row]
                                  for row in pattern])
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError('Camera RAW has an invalid Bayer colour description') from exc
        cfa_pattern = ''.join(letters.ravel())
        if cfa_pattern not in SUPPORTED_CFA:
            raise ValueError(f'Camera RAW does not use a supported Bayer pattern: {cfa_pattern}')

        native = np.array(mosaic, copy=True)
        by_name = {}
        colour_indices = {}
        green_number = 0
        for row in range(2):
            for col in range(2):
                name = letters[row, col]
                if name == 'G':
                    green_number += 1
                    name = f'G{green_number}'
                by_name[name] = np.array(native[row::2, col::2], copy=True)
                colour_indices[name] = int(pattern[row, col])
        if set(by_name) != set(PLANE_NAMES):
            raise ValueError(f'Camera RAW does not define exactly R, G1, G2 and B: {cfa_pattern}')
        shape = next(iter(by_name.values())).shape
        if any(plane.shape != shape for plane in by_name.values()):
            raise ValueError('Camera RAW Bayer planes do not have equal dimensions')

        black_by_index = list(raw.black_level_per_channel)
        camera_white = getattr(raw, 'camera_white_level_per_channel', None)
        camera_white = list(camera_white) if camera_white is not None else []
        global_white = float(raw.white_level)
        try:
            black_levels = {name: float(black_by_index[colour_indices[name]])
                            for name in PLANE_NAMES}
            white_levels = {
                name: float(camera_white[colour_indices[name]])
                if (colour_indices[name] < len(camera_white)
                    and camera_white[colour_indices[name]] not in (None, 0))
                else global_white
                for name in PLANE_NAMES
            }
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError('Camera RAW calibration levels do not match its Bayer indices') from exc

        details = {
            'decoder': 'rawpy/libraw',
            'cfa_pattern': cfa_pattern,
            'sensor_visible_shape': [int(native.shape[0]), int(native.shape[1])],
            'stored_dtype': str(native.dtype),
            'white_level': global_white,
            'exposure_seconds': exif.get(
                'exposure_seconds', _plain(getattr(raw, 'shutter', None))),
            'iso': exif.get('iso', _plain(getattr(raw, 'iso_speed', None))),
            'camera_make': exif.get(
                'camera_make', _plain(getattr(raw, 'camera_make', None))),
            'camera_model': exif.get(
                'camera_model', _plain(getattr(raw, 'camera_model', None))),
            'lens': exif.get('lens', _plain(getattr(raw, 'lens', None))),
        }
    return CameraRawImage(
        planes={name: by_name[name] for name in PLANE_NAMES},
        black_levels=black_levels,
        white_levels=white_levels,
        details=details,
    )
