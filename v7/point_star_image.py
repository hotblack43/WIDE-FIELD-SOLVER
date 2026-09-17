"""Native-depth scientific image loading for the v7 solver.

Scientific samples stay in their decoded numeric units.  The uint8 RGB member
is a one-way display product and must never be used for measurements.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from astropy.io import fits
import numpy as np
from PIL import Image


class ImageLayoutError(ValueError):
    """The file contains pixels but their scientific meaning is ambiguous."""


@dataclass(frozen=True)
class ScientificImage:
    path: Path
    planes: Mapping[str, np.ndarray]
    rgb: np.ndarray | None
    luminance: np.ndarray
    valid_mask: np.ndarray
    saturated_mask: np.ndarray
    plane_saturated_masks: Mapping[str, np.ndarray]
    display_rgb: np.ndarray
    metadata: Mapping[str, object]

    @property
    def shape(self):
        return self.luminance.shape

    def provenance(self):
        return dict(self.metadata)


def _channel_names(count, order=None):
    compact = None if order is None else ''.join(str(order).upper().replace(',', '').split())
    if compact is not None:
        aliases = {'RGB': ('R', 'G', 'B'), 'RGGB': ('R', 'G1', 'G2', 'B'),
                   'RG1G2B': ('R', 'G1', 'G2', 'B')}
        if compact not in aliases or len(aliases[compact]) != count:
            raise ImageLayoutError(
                f"Channel order {order!r} does not describe {count} planes; use RGB or RG1G2B")
        return aliases[compact]
    if count == 3:
        return ('R', 'G', 'B')
    if count == 4:
        return ('R', 'G1', 'G2', 'B')
    raise ImageLayoutError(f'Only monochrome, RGB and RG1G2B images are supported, not {count} planes')


def _split_array(array, *, channel_order=None):
    values = np.asarray(array)
    if values.ndim == 2:
        return {'L': values}, 'two_dimensional'
    if values.ndim != 3:
        raise ImageLayoutError(
            f'Expected a 2-D image or 3/4-plane stack; decoded shape is {values.shape}')
    first = values.shape[0] in (3, 4)
    last = values.shape[-1] in (3, 4)
    if first and last:
        raise ImageLayoutError(
            f'Channel axis is ambiguous for shape {values.shape}; specify a non-ambiguous stack')
    if not first and not last:
        raise ImageLayoutError(
            f'No 3/4-plane channel axis is present in decoded shape {values.shape}')
    if first:
        names = _channel_names(values.shape[0], channel_order)
        return {name: values[index] for index, name in enumerate(names)}, 'plane_first'
    names = _channel_names(values.shape[-1], channel_order)
    return {name: values[..., index] for index, name in enumerate(names)}, 'plane_last'


def _read_png(path):
    import png
    with path.open('rb') as handle:
        width, height, rows, info = png.Reader(file=handle).read()
        if info.get('alpha') or info.get('palette') is not None:
            raise ImageLayoutError('PNG alpha/palette input needs an explicit scientific channel policy')
        bit_depth = int(info['bitdepth'])
        dtype = np.uint8 if bit_depth <= 8 else np.uint16
        flat = np.vstack([np.asarray(row, dtype=dtype) for row in rows])
    count = int(info['planes'])
    array = flat.reshape(height, width) if count == 1 else flat.reshape(height, width, count)
    return array, {'decoder': 'pypng', 'stored_bit_depth': bit_depth}


def _read_raster(path):
    suffix = path.suffix.lower()
    if suffix == '.png':
        return _read_png(path)
    if suffix in ('.tif', '.tiff'):
        import tifffile
        return tifffile.imread(path), {'decoder': 'tifffile'}
    with Image.open(path) as image:
        if image.mode in ('P', 'RGBA', 'LA'):
            raise ImageLayoutError(
                f'{image.mode} input needs an explicit scientific palette/alpha policy')
        return np.asarray(image).copy(), {'decoder': 'pillow', 'stored_mode': image.mode}


def _explicit_levels(value, names):
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key).upper(): float(level) for key, level in value.items()}
    if isinstance(value, str) and '=' in value:
        answer = {}
        for item in value.split(','):
            key, level = item.split('=', 1)
            answer[key.strip().upper()] = float(level)
        return answer
    return {name: float(value) for name in names}


def _saturation(planes, *, rendered_uint8=False, explicit=None, header_levels=None):
    masks = {}
    records = {}
    combined = np.zeros(next(iter(planes.values())).shape, dtype=bool)
    explicit = _explicit_levels(explicit, planes)
    header_levels = header_levels or {}
    for name, plane in planes.items():
        decoded_dtype = np.asarray(plane).dtype
        if name in explicit:
            level, source, confidence, known = explicit[name], 'explicit', 'established', True
        elif name in header_levels:
            level, source, confidence, known = (float(header_levels[name]), 'fits_SATURATE',
                                                'established', True)
        elif rendered_uint8:
            level, source, confidence, known = 250., 'v7_uint8_compatibility', 'established', True
        elif np.issubdtype(decoded_dtype, np.integer):
            observed = float(np.nanmax(plane))
            standards = (255., 1023., 4095., 16383., 65535.)
            if observed in standards:
                level, source, confidence = observed, 'observed_standard_clipping_ceiling', 'conditional'
            else:
                level = float(np.iinfo(decoded_dtype).max)
                source, confidence = 'datatype_ceiling_assumption', 'assumed'
            known = True
        else:
            level, source, confidence, known = None, 'unavailable_for_floating_input', 'unknown', False
        mask = np.zeros(plane.shape, bool) if level is None else np.asarray(plane >= level)
        masks[name] = mask
        combined |= mask
        records[name] = dict(level=level, source=source, confidence=confidence, known=known)
    return masks, combined, records


def _fits_hdu_record(hdu, index, header=None):
    header = hdu.header if header is None else header
    return dict(index=index, name=hdu.name, bitpix=header.get('BITPIX'),
                bscale=header.get('BSCALE', 1), bzero=header.get('BZERO', 0))


def _read_fits(path, *, fits_hdu=None, channel_order=None):
    with fits.open(path, memmap=False) as hdus:
        original_headers = [hdu.header.copy() for hdu in hdus]
        candidates = [(index, hdu) for index, hdu in enumerate(hdus)
                      if getattr(hdu, 'data', None) is not None
                      and np.asarray(hdu.data).ndim in (2, 3)]
        named = {hdu.name.upper(): (index, hdu) for index, hdu in candidates}
        def named_plane(*aliases):
            return next((named[alias] for alias in aliases if alias in named), None)
        red, blue = named_plane('RED', 'R'), named_plane('BLUE', 'B')
        green1, green2 = named_plane('GREEN1', 'G1'), named_plane('GREEN2', 'G2')
        green = named_plane('GREEN', 'G', 'GREENAVERAGE', 'GAVERAGE', 'GAVG')
        if fits_hdu is None and all(value is not None for value in (red, green1, green2, blue)):
            selected = [('R', red), ('G1', green1), ('G2', green2), ('B', blue)]
        elif fits_hdu is None and all(value is not None for value in (red, green, blue)):
            selected = [('R', red), ('G', green), ('B', blue)]
        else:
            if fits_hdu is not None:
                selector = int(fits_hdu) if isinstance(fits_hdu, str) and fits_hdu.isdigit() else fits_hdu
                try:
                    chosen = hdus[selector]
                except (IndexError, KeyError) as error:
                    available = ', '.join(f'{index}:{hdu.name}' for index, hdu in candidates)
                    raise ImageLayoutError(
                        f'FITS HDU {fits_hdu!r} is unavailable; image HDUs are {available}') from error
                if getattr(chosen, 'data', None) is None or np.asarray(chosen.data).ndim not in (2, 3):
                    raise ImageLayoutError(f'FITS HDU {fits_hdu!r} is not a 2-D image or 3/4-plane stack')
                selected = None
                chosen_index = hdus.index_of(chosen)
            elif len(candidates) == 1:
                chosen_index, chosen = candidates[0]
                selected = None
            elif not candidates:
                raise ImageLayoutError('FITS file contains no supported 2-D image or 3/4-plane stack')
            else:
                choices = ', '.join(f'{index}:{hdu.name}' for index, hdu in candidates)
                raise ImageLayoutError(
                    f'FITS contains multiple plausible image HDUs ({choices}); select one with --fits-hdu')
        if selected is not None:
            shapes = {tuple(np.asarray(hdu.data).shape) for _, (_, hdu) in selected}
            if len(shapes) != 1 or len(next(iter(shapes))) != 2:
                raise ImageLayoutError('Named FITS colour extensions must be equally shaped 2-D images')
            planes = {name: np.asarray(hdu.data).copy() for name, (_, hdu) in selected}
            records = [_fits_hdu_record(hdu, index, original_headers[index])
                       for _, (index, hdu) in selected]
            levels = {name: original_headers[index]['SATURATE']
                      for name, (index, hdu) in selected
                      if 'SATURATE' in original_headers[index]}
            layout = 'named_extensions'
        else:
            values = np.asarray(chosen.data).copy()
            planes, layout = _split_array(values, channel_order=channel_order)
            records = [_fits_hdu_record(chosen, chosen_index, original_headers[chosen_index])]
            original = original_headers[chosen_index]
            levels = ({name: original['SATURATE'] for name in planes}
                      if 'SATURATE' in original else {})
        details = dict(decoder='astropy.io.fits', fits_hdus=records,
                       fits_hdu_selection=('named_colour_extensions' if selected is not None
                                           else str(chosen_index)))
        return planes, layout, details, levels


def _display(planes, rgb):
    if rgb is not None and all(np.asarray(planes[name]).dtype == np.uint8 for name in ('R', 'G', 'B')):
        return np.asarray(rgb, dtype=np.uint8).copy(), 'native_uint8_rgb'
    source = (np.repeat(next(iter(planes.values()))[..., None], 3, axis=2)
              if rgb is None else np.asarray(rgb))
    display = np.zeros(source.shape, dtype=np.uint8)
    for index in range(3):
        values = np.asarray(source[..., index], dtype=float)
        finite = np.isfinite(values)
        if not finite.any():
            continue
        low, high = np.percentile(values[finite], [0.5, 99.5])
        if high <= low:
            high = low + 1.
        scaled = np.zeros(values.shape, dtype=float)
        scaled[finite] = (values[finite]-low)*255./(high-low)
        display[..., index] = np.clip(np.rint(scaled), 0, 255).astype(np.uint8)
    return display, 'finite_0.5_99.5_percentile_per_channel'


def load_scientific_image(path, *, fits_hdu=None, channel_order=None, saturation_level=None):
    """Decode an image without quantising its scientific samples."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    suffix = path.suffix.lower()
    if suffix in ('.fits', '.fit', '.fts'):
        planes, layout, details, header_levels = _read_fits(
            path, fits_hdu=fits_hdu, channel_order=channel_order)
        rendered_uint8 = False
        decoded_shape = ([len(planes), *next(iter(planes.values())).shape]
                         if len(planes) > 1 else list(next(iter(planes.values())).shape))
    else:
        array, details = _read_raster(path)
        planes, layout = _split_array(array, channel_order=channel_order)
        header_levels = {}
        rendered_uint8 = array.dtype == np.uint8
        decoded_shape = list(array.shape)
    planes = {name: np.asarray(value).copy() for name, value in planes.items()}
    if set(planes) == {'R', 'G', 'B'}:
        rgb = np.stack([planes[name].astype(float) for name in ('R', 'G', 'B')], axis=-1)
    elif set(planes) == {'R', 'G1', 'G2', 'B'}:
        rgb = np.stack([planes['R'].astype(float),
                        (planes['G1'].astype(float)+planes['G2'].astype(float))/2.,
                        planes['B'].astype(float)], axis=-1)
    else:
        rgb = None
    if rgb is None:
        luminance = next(iter(planes.values())).astype(float)
    else:
        luminance = rgb @ np.array([.2126, .7152, .0722])
    valid = np.ones(luminance.shape, dtype=bool)
    for plane in planes.values():
        valid &= np.isfinite(plane)
    masks, saturated, definitions = _saturation(
        planes, rendered_uint8=rendered_uint8, explicit=saturation_level,
        header_levels=header_levels)
    display, display_method = _display(planes, rgb)
    effective_bits = {}
    for name, plane in planes.items():
        level = definitions[name]['level']
        if level is not None and level >= 1:
            effective_bits[name] = int(np.ceil(np.log2(level+1)))
        elif np.issubdtype(plane.dtype, np.integer):
            effective_bits[name] = int(np.iinfo(plane.dtype).bits)
        else:
            effective_bits[name] = None
    metadata = dict(
        source=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        format=suffix.lstrip('.'),
        decoded_dtype=({name: str(value.dtype) for name, value in planes.items()}),
        decoded_shape=decoded_shape, spatial_shape=list(luminance.shape),
        plane_names=list(planes), channel_layout=layout,
        channel_derivation={'G': '(G1 + G2) / 2'} if 'G1' in planes else {},
        invalid_pixel_count=int((~valid).sum()), saturation=definitions,
        saturation_known=all(item['known'] for item in definitions.values()),
        effective_bit_depth=effective_bits,
        black_level=dict(status='not_applied', level=None,
                         reason='No trustworthy black-level metadata or explicit setting supplied'),
        display_method=display_method, native_depth_preserved=True, **details)
    metadata['load_policy'] = dict(
        fits_hdu=fits_hdu, channel_order=channel_order,
        saturation_level=(dict(saturation_level) if isinstance(saturation_level, Mapping)
                          else saturation_level))
    return ScientificImage(path, MappingProxyType(planes), rgb, luminance, valid,
                           saturated, MappingProxyType(masks), display,
                           MappingProxyType(metadata))


def load_recorded_image(path, solution):
    """Reload with the detection-stage policy and verify immutable source bytes."""
    solution = Path(solution)
    candidates = [solution/'input_image.json', solution/'dots/input_image.json']
    record_path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if record_path is None:
        return load_scientific_image(path)
    record = json.loads(record_path.read_text())
    source = Path(path).expanduser().resolve()
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != record.get('source_sha256'):
        raise ValueError('Original image checksum differs from recorded scientific input')
    policy = record.get('load_policy') or {}
    image = load_scientific_image(source, **policy)
    if image.provenance()['source_sha256'] != record.get('source_sha256'):
        raise ValueError('Reloaded image checksum differs from recorded scientific input')
    return image
