"""Resolve post-fit observation times for metadata-conditioned planet checks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from astropy.io import fits
from astropy.time import Time
from PIL import Image, UnidentifiedImageError


from point_star_image import fits_image_suffix
_EXIF_FIELDS = (
    (36867, 'DateTimeOriginal', 36881),
    (36868, 'DateTimeDigitized', 36882),
    (306, 'DateTime', 36880),
)
_ISO_FILENAME = re.compile(
    r'(?<!\d)(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)')
_COMPACT_FILENAME = re.compile(r'(?<!\d)(\d{8}T\d{6}(?:\.\d+)?Z)(?!\d)')


def _datetime_time(value: str, *, exif=False, offset=None):
    text = str(value).strip()
    if exif:
        parsed = datetime.strptime(text, '%Y:%m:%d %H:%M:%S')
        if offset:
            match = re.fullmatch(r'([+-])(\d{2}):(\d{2})', str(offset).strip())
            if not match:
                raise ValueError('invalid EXIF UTC offset')
            minutes = int(match.group(2))*60 + int(match.group(3))
            if match.group(1) == '-':
                minutes = -minutes
            parsed = parsed.replace(tzinfo=timezone(timedelta(minutes=minutes)))
            assumed_utc = False
        else:
            parsed = parsed.replace(tzinfo=timezone.utc)
            assumed_utc = True
    else:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        parsed = datetime.fromisoformat(text)
        assumed_utc = parsed.tzinfo is None
        if assumed_utc:
            parsed = parsed.replace(tzinfo=timezone.utc)
    return Time(parsed.astimezone(timezone.utc), scale='utc'), assumed_utc


def _row(instant, *, source, field, value, assumed_utc, priority):
    instant = instant.utc
    instant.precision = 3
    return dict(source=source, field=field, value=str(value),
                time_utc=instant.isot+' UTC', jd_utc=float(instant.jd),
                assumed_utc=bool(assumed_utc), _priority=int(priority))


def _fits_candidates(path):
    if not fits_image_suffix(path):
        return []
    rows = []
    try:
        with fits.open(path, memmap=False) as hdus:
            primary_timesys = str(hdus[0].header.get('TIMESYS', 'UTC')).lower()
            for index, hdu in enumerate(hdus):
                header = hdu.header
                label = 'PRIMARY' if index == 0 else (hdu.name or str(index))
                scale = str(header.get('TIMESYS', primary_timesys)).lower()
                for rank, field in enumerate(('DATE-OBS', 'MJD-OBS', 'JD')):
                    if field not in header:
                        continue
                    raw = header[field]
                    assumed = 'TIMESYS' not in header and 'TIMESYS' not in hdus[0].header
                    try:
                        if field == 'DATE-OBS' and re.search(r'(?:Z|[+-]\d{2}:?\d{2})$', str(raw)):
                            instant, date_assumed = _datetime_time(raw)
                            assumed = assumed or date_assumed
                        elif field == 'DATE-OBS':
                            instant = Time(str(raw), scale=scale).utc
                        else:
                            instant = Time(float(raw), format='mjd' if field == 'MJD-OBS' else 'jd',
                                           scale=scale).utc
                    except (TypeError, ValueError):
                        continue
                    rows.append(_row(instant, source=f'fits:{label}:{field}',
                                     field=field, value=raw, assumed_utc=assumed,
                                     priority=10*index+rank))
    except (OSError, ValueError, TypeError):
        return []
    return rows


def _exif_candidates(path):
    if fits_image_suffix(path) or path.suffix.lower() == '.cr2':
        return []
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            rows = []
            for rank, (tag, field, offset_tag) in enumerate(_EXIF_FIELDS):
                if tag not in exif:
                    continue
                instant, assumed = _datetime_time(
                    exif[tag], exif=True, offset=exif.get(offset_tag))
                rows.append(_row(instant, source=f'exif:{field}', field=field,
                                 value=exif[tag], assumed_utc=assumed,
                                 priority=100+rank))
            return rows
    except (OSError, ValueError, TypeError, UnidentifiedImageError):
        return []


def _camera_raw_candidates(path):
    if path.suffix.lower() != '.cr2':
        return []
    from point_star_raw import read_cr2_exif
    metadata = read_cr2_exif(path, {
        'datetime_original', 'datetime_digitized', 'datetime',
        'offset_time_original', 'offset_time_digitized', 'offset_time'})
    rows = []
    definitions = (
        ('datetime_original', 'DateTimeOriginal', 'offset_time_original'),
        ('datetime_digitized', 'DateTimeDigitized', 'offset_time_digitized'),
        ('datetime', 'DateTime', 'offset_time'),
    )
    for rank, (field, label, offset_field) in enumerate(definitions):
        if field not in metadata:
            continue
        offset = metadata.get(offset_field) or metadata.get('offset_time')
        try:
            instant, assumed = _datetime_time(metadata[field], exif=True, offset=offset)
        except (TypeError, ValueError):
            continue
        rows.append(_row(instant, source=f'cr2_exif:{label}', field=label,
                         value=metadata[field], assumed_utc=assumed,
                         priority=100+rank))
    return rows


def _filename_candidates(path):
    name = path.name
    match = _ISO_FILENAME.search(name)
    compact = False
    if match is None:
        match = _COMPACT_FILENAME.search(name)
        compact = match is not None
    if match is None:
        return []
    raw = match.group(1)
    value = raw
    if compact:
        value = (raw[:4]+'-'+raw[4:6]+'-'+raw[6:8]+'T'+raw[9:11]+':'
                 +raw[11:13]+':'+raw[13:])
    instant, assumed = _datetime_time(value)
    return [_row(instant, source='filename', field='filename_timestamp',
                 value=raw, assumed_utc=assumed, priority=200)]


def resolve_observation_time(path, explicit_time=None):
    """Select a UTC observation time and retain every parseable alternative."""
    path = Path(path)
    rows = []
    if explicit_time:
        instant, assumed = _datetime_time(explicit_time)
        rows.append(_row(instant, source='explicit_argument', field='observation_time',
                         value=explicit_time, assumed_utc=assumed, priority=-1))
    rows.extend(_fits_candidates(path))
    rows.extend(_camera_raw_candidates(path))
    rows.extend(_exif_candidates(path))
    rows.extend(_filename_candidates(path))
    rows.sort(key=lambda row: row['_priority'])
    if not rows:
        return dict(status='unavailable', time_utc=None, source=None,
                    assumed_utc=None, disagreement=False,
                    maximum_disagreement_seconds=0., candidates=[])
    selected = rows[0]
    disagreements = [abs((row['jd_utc']-selected['jd_utc'])*86400.) for row in rows]
    for row, seconds in zip(rows, disagreements):
        row['difference_from_selected_seconds'] = float(seconds)
        row['selected'] = row is selected
        row.pop('_priority')
    maximum = max(disagreements, default=0.)
    return dict(status='selected', time_utc=selected['time_utc'],
                jd_utc=selected['jd_utc'], source=selected['source'],
                field=selected['field'], assumed_utc=selected['assumed_utc'],
                disagreement=bool(maximum > 1.),
                maximum_disagreement_seconds=float(maximum), candidates=rows)


def planet_search_context(path, *, explicit_time=None, force_blind=False,
                          latest_jd_tdb=None, half_width_days=1.):
    """Choose metadata-conditioned or full blind planet-search bounds."""
    full = (1850., 2036.)
    if force_blind:
        return dict(planet_search_mode='blind_forced', metadata_used=False,
                    epoch_limits=full, observation_time_metadata={
                        'status': 'skipped',
                        'reason': 'Full blind planet search explicitly requested'})
    resolved = resolve_observation_time(path, explicit_time=explicit_time)
    if resolved['status'] != 'selected':
        return dict(planet_search_mode='blind_fallback', metadata_used=False,
                    epoch_limits=full, observation_time_metadata=resolved,
                    metadata_fallback_reason='No usable EXIF, FITS or filename observation time')
    centre = Time(resolved['jd_utc'], format='jd', scale='utc').tdb.jd
    first, last = Time(full, format='jyear', scale='tdb').jd
    if latest_jd_tdb is not None:
        last = min(last, float(latest_jd_tdb))
    if not (first <= centre <= last):
        resolved['rejection_reason'] = 'Observation time lies outside the supported causal interval'
        return dict(planet_search_mode='blind_fallback', metadata_used=False,
                    epoch_limits=full, observation_time_metadata=resolved,
                    metadata_fallback_reason=resolved['rejection_reason'])
    start = max(first, centre-float(half_width_days))
    stop = min(last, centre+float(half_width_days))
    if stop <= start:
        resolved['rejection_reason'] = 'Observation-time search interval is empty'
        return dict(planet_search_mode='blind_fallback', metadata_used=False,
                    epoch_limits=full, observation_time_metadata=resolved,
                    metadata_fallback_reason=resolved['rejection_reason'])
    limits = tuple(float(value) for value in Time([start, stop], format='jd', scale='tdb').jyear)
    resolved['jd_tdb'] = float(centre)
    return dict(planet_search_mode='metadata_conditioned', metadata_used=True,
                epoch_limits=limits, metadata_search_half_width_days=float(half_width_days),
                observation_time_metadata=resolved)
