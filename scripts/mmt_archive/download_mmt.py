#!/usr/bin/env python3
"""Inventory and download one fully moonless MMTO astronomical night.

Standalone; no solver imports. See README.md for the inspected timing anomaly,
sources, horizon convention, and the distinction between archive completeness
and uninterrupted coverage. Originals are never rewritten as FITS.
"""
from __future__ import annotations

import argparse
import bz2
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import time
import warnings
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from zoneinfo import ZoneInfo

import astropy
import numpy as np
import requests
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, get_body
from astropy.io import fits
from astropy.time import Time
from astropy.utils import iers
from scipy.optimize import brentq, minimize_scalar

BASE = 'https://skycam.mmto.arizona.edu/skycam/archive/'
LOCAL = ZoneInfo('America/Phoenix')
UTC = timezone.utc
LAT = 31 + 41 / 60 + 12 / 3600
LON = -(110 + 53 / 60 + 3 / 3600)
ELEVATION = 2616.0  # Published summit elevation; no surveyed camera height available.
REFRACTION = 34 / 60
RATE_BOUND = 0.01  # deg/s, >2x lunar diurnal + orbital + parallax angular speed.
EPHEMERIS_MARGIN = 0.02  # degrees, deliberately conservative for builtin ephemeris.
FITS_NAME = re.compile(r'\.(?:fits|fit|fts)\.bz2$', re.I)
STAMP = re.compile(r'^(\d{4}_\d{2}_\d{2}__\d{2}_\d{2}_\d{2})\.')
FIELDS = ['source_url', 'filename', 'archive_date', 'listed_bytes_approx',
          'remote_bytes', 'date_obs_raw', 'date_created_raw', 'timestamp_convention',
          'exposure_seconds', 'utc_start', 'utc_mid', 'utc_end',
          'sun_alt_start_deg', 'sun_alt_mid_deg', 'sun_alt_end_deg',
          'moon_alt_start_deg', 'moon_alt_mid_deg', 'moon_alt_end_deg',
          'moon_upper_limb_max_bound_deg', 'eligible', 'download_status',
          'validation_status', 'compressed_bytes', 'sha256', 'fits_sha256',
          'fits_shapes', 'local_path', 'decompression_status', 'decompression_error', 'error']


def utc_text(value):
    return value.astimezone(UTC).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def parse_utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def write_csv(path, rows, fields=FIELDS):
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.extend(v for k, v in attrs if k == 'href' and v)


def fits_links(html, base):
    """The observed lighttpd listing incorrectly appends '/' to file links."""
    parser = Links()
    parser.feed(html)
    found = {}
    for href in parser.hrefs:
        url = urljoin(base, href).rstrip('/')
        parsed = urlsplit(url)
        name = unquote(parsed.path.rsplit('/', 1)[-1])
        if (url.rsplit('/', 1)[0] + '/' != base or parsed.query or
                '/' in name or '\\' in name or not FITS_NAME.search(name)):
            continue
        # Listing sizes are rounded; only Content-Length is used for validation.
        match = re.search(r'href="' + re.escape(href) + r'".*?<td class="s">([^<]+)',
                          html, flags=re.S)
        approx = 0
        if match:
            size = re.search(r'([\d.]+)([KMGT]?)', match.group(1))
            if size:
                approx = int(float(size[1]) * 1024 ** (' KMGT'.index(size[2]) if size[2] else 0))
        found[url] = dict(source_url=url, filename=name,
                          archive_date=base.rstrip('/').rsplit('/', 1)[-1],
                          listed_bytes_approx=approx, eligible='unknown',
                          download_status='pending_header', validation_status='not_checked', error='')
    return sorted(found.values(), key=lambda row: row['filename'])


def sexagesimal(value):
    parts = str(value).strip().split(':')
    if len(parts) != 4 or float(parts[3]) != 0:
        raise ValueError(f'Unrecognized MMTO coordinate format: {value!r}')
    sign = -1 if parts[0].startswith('-') else 1
    return sign * (abs(float(parts[0])) + float(parts[1]) / 60 + float(parts[2]) / 3600)


def exposure_metadata(header, filename):
    """Inspected Skywatch 4.3.15 convention; reject inconsistent future formats.

    DATE-OBS and UT are actually local MST, notwithstanding their UT comments.
    DATE is UTC creation. Adjacent archive JPEG explicitly says LT. Preserve both.
    """
    for key, expected in [('SITELAT', LAT), ('SITELONG', LON)]:
        if abs(sexagesimal(header[key]) - expected) > 0.0001:
            raise ValueError(f'{key} differs from verified camera site')
    if float(header.get('STACKNB', 1)) != 1:
        raise ValueError('Stacked image duration is not established; refusing to guess')
    seconds = float(header.get('EXPOSURE', header.get('EXPTIME', 'nan')))
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('Missing/nonpositive/nonfinite exposure duration')
    start_naive = datetime.fromisoformat(header['DATE-OBS'])
    if start_naive.tzinfo is not None:
        raise ValueError('DATE-OBS clock format changed; inspect before proceeding')
    start = start_naive.replace(tzinfo=LOCAL).astimezone(UTC)
    end = start + timedelta(seconds=seconds)
    created = datetime.fromisoformat(header['DATE']).replace(tzinfo=UTC)
    lag = (created - end).total_seconds()
    if not 0 <= lag <= 120:
        raise ValueError(f'DATE versus local DATE-OBS inconsistent: post-exposure lag {lag:.3f}s')
    stamp = STAMP.match(filename)
    if stamp:
        named = datetime.strptime(stamp[1], '%Y_%m_%d__%H_%M_%S').replace(tzinfo=LOCAL)
        if abs((named.astimezone(UTC) - created).total_seconds()) > 2:
            raise ValueError('Filename and FITS DATE disagree with inspected local clock')
    return dict(date_obs_raw=header['DATE-OBS'], date_created_raw=header['DATE'],
                timestamp_convention='DATE-OBS local America/Phoenix despite UT comment; DATE UTC',
                exposure_seconds=seconds, utc_start=utc_text(start), utc_end=utc_text(end),
                utc_mid=utc_text(start + timedelta(seconds=seconds / 2)))


def wholly_inside(start, end, dark_start, dark_end):
    return dark_start < start <= end < dark_end


def interval_upper_bound(values, spacing):
    """Enclose between samples with a conservative angular-rate bound."""
    return float(np.max(values)) + RATE_BOUND * spacing / 2 + EPHEMERIS_MARGIN


def archive_dates(start, end):
    # Skywatch's documented local-noon to local-noon archive buckets.
    first = (parse_utc(start).astimezone(LOCAL) - timedelta(hours=12)).date()
    last = (parse_utc(end).astimezone(LOCAL) - timedelta(hours=12)).date()
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


class Astronomy:
    def __init__(self):
        iers.conf.auto_download = False
        self.site = EarthLocation.from_geodetic(LON * u.deg, LAT * u.deg, ELEVATION * u.m)
        self.dip = math.degrees(math.acos(6371000 / (6371000 + ELEVATION)))

    def positions(self, unix):
        t = Time(unix, format='unix', scale='utc')
        frame = AltAz(obstime=t, location=self.site, pressure=0 * u.hPa)
        sun = get_body('sun', t, self.site, ephemeris='builtin').transform_to(frame).alt.deg
        moon = get_body('moon', t, self.site, ephemeris='builtin')
        altitude = moon.transform_to(frame).alt.deg
        radius = np.degrees(np.arcsin(1737.4 / moon.distance.to_value(u.km)))
        return sun, altitude, altitude + radius + REFRACTION + self.dip

    def night(self, local_date):
        noon = datetime.combine(local_date, datetime.min.time(), LOCAL) + timedelta(hours=12)
        base = noon.timestamp()
        grid = base + np.arange(0, 86401, 600)
        solar = self.positions(grid)[0] + 18
        events = []
        for i in range(len(grid) - 1):
            if solar[i] * solar[i + 1] < 0:
                root = brentq(lambda x: float(self.positions(x)[0]) + 18,
                              grid[i], grid[i + 1], xtol=0.001)
                events.append((root, solar[i] > 0))
        if len(events) != 2 or not events[0][1] or events[1][1]:
            return dict(local_observing_date=str(local_date), qualifies=False,
                        reason='No single complete astronomical-darkness interval')
        start, end = events[0][0], events[1][0]
        grid = np.linspace(start, end, math.ceil((end - start) / 60) + 1)
        sun, moon, upper = self.positions(grid)
        spacing = float(grid[1] - grid[0])
        bound = interval_upper_bound(upper, spacing)
        # Refine each sampled maximum, and check every sign crossing explicitly.
        maxima = [(float(upper[0]), start), (float(upper[-1]), end)]
        for i in range(1, len(grid) - 1):
            if upper[i] >= upper[i - 1] and upper[i] >= upper[i + 1]:
                opt = minimize_scalar(lambda x: -float(self.positions(x)[2]),
                                      bounds=(grid[i - 1], grid[i + 1]), method='bounded',
                                      options={'xatol': 0.001})
                maxima.append((-float(opt.fun), float(opt.x)))
        crossings = []
        for i in range(len(grid) - 1):
            if upper[i] * upper[i + 1] < 0:
                root = brentq(lambda x: float(self.positions(x)[2]), grid[i], grid[i + 1], xtol=.001)
                crossings.append(utc_text(datetime.fromtimestamp(root, UTC)))
        peak, peak_time = max(maxima)
        self.track = [dict(utc=utc_text(datetime.fromtimestamp(float(t), UTC)),
                           sun_center_deg=float(s), moon_center_deg=float(m),
                           moon_upper_limb_relative_horizon_deg=float(v))
                      for t, s, m, v in zip(grid, sun, moon, upper)]
        return dict(local_observing_date=str(local_date),
                    dark_start_utc=utc_text(datetime.fromtimestamp(start, UTC)),
                    dark_end_utc=utc_text(datetime.fromtimestamp(end, UTC)),
                    dark_duration_seconds=end - start, qualifies=bound < 0,
                    moon_center_sampled_max_deg=float(np.max(moon)),
                    moon_upper_limb_refined_max_relative_horizon_deg=peak,
                    moon_upper_limb_peak_utc=utc_text(datetime.fromtimestamp(peak_time, UTC)),
                    moon_upper_limb_bound_relative_horizon_deg=bound,
                    moon_horizon_crossings_utc=crossings, sample_spacing_seconds=spacing,
                    horizon_dip_deg=self.dip, horizon_refraction_deg=REFRACTION,
                    ephemeris_margin_deg=EPHEMERIS_MARGIN,
                    reason='Full interval upper bound below horizon' if bound < 0 else 'Moon test failed')

    def annotate(self, rows, night):
        valid = [r for r in rows if r.get('utc_start')]
        start = parse_utc(night['dark_start_utc']).timestamp()
        end = parse_utc(night['dark_end_utc']).timestamp()
        for offset in range(0, len(valid), 200):
            batch = valid[offset:offset + 200]
            times = np.array([[parse_utc(r[f'utc_{k}']).timestamp()
                               for k in ('start', 'mid', 'end')] for r in batch])
            sun, moon, upper = self.positions(times.ravel())
            sun, moon, upper = [v.reshape(-1, 3) for v in (sun, moon, upper)]
            for i, row in enumerate(batch):
                for j, key in enumerate(('start', 'mid', 'end')):
                    row[f'sun_alt_{key}_deg'] = float(sun[i, j])
                    row[f'moon_alt_{key}_deg'] = float(moon[i, j])
                row['moon_upper_limb_max_bound_deg'] = night['moon_upper_limb_bound_relative_horizon_deg']
                eligible = wholly_inside(times[i, 0], times[i, 2], start, end)
                row['eligible'] = str(eligible).lower()
                if row['download_status'] in ('pending_header', 'pending_download', 'not_selected'):
                    row['download_status'] = 'pending_download' if eligible else 'not_selected'


class HTTP:
    def __init__(self, timeout=45, retries=3, delay=.5):
        self.timeout, self.retries, self.delay = timeout, retries, delay
        self.local = threading.local()
        self.pacing_lock = threading.Lock()
        self.last_request = 0.0

    def session(self):
        if not hasattr(self.local, 'session'):
            self.local.session = requests.Session()
            self.local.session.headers.update({'User-Agent': 'MMTO-moonless-archive-downloader/1.0',
                                                'Accept-Encoding': 'identity'})
        return self.local.session

    def fetch(self, url, consumer):
        error = None
        for attempt in range(self.retries + 1):
            with self.pacing_lock:
                time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
            try:
                with self.session().get(url, timeout=(min(20, self.timeout), self.timeout), stream=True) as r:
                    r.raise_for_status()
                    return consumer(r)
            except (requests.RequestException, ValueError, OSError, EOFError) as exc:
                error = exc
                if isinstance(exc, requests.HTTPError) and exc.response.status_code in (400, 401, 403, 404):
                    break
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 16))
        raise RuntimeError(f'{url}: {error}') from error

    def text(self, url):
        return self.fetch(url, lambda response: response.text)

    def header(self, url):
        def consume(response):
            decoder = bz2.BZ2Decompressor()
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(decoder.decompress(chunk, max_length=1048576 - len(raw)))
                for pos in range(0, len(raw) - 79, 80):
                    if raw[pos:pos + 8] == b'END     ':
                        header = fits.Header.fromstring(bytes(raw[:pos + 80]).decode('ascii'))
                        if not header.get('SIMPLE'):
                            raise ValueError('Not a primary FITS header')
                        return header, int(response.headers.get('Content-Length', 0))
                if len(raw) >= 1048576 or decoder.eof:
                    break
            raise ValueError('Cannot read primary FITS header from bz2 prefix')
        return self.fetch(url, consume)

    def download(self, url, path):
        def consume(response):
            expected = int(response.headers.get('Content-Length', 0))
            part = path.with_name(path.name + '.part')
            try:
                with part.open('wb') as out:
                    for chunk in response.iter_content(262144):
                        out.write(chunk)
                if expected and part.stat().st_size != expected:
                    raise ValueError('Content-Length mismatch')
                info, raw = validate_file(part)
                part.replace(path)
                return info, raw
            finally:
                part.unlink(missing_ok=True)
        return self.fetch(url, consume)


def validate_file(path):
    try:
        return _validate_file(path)
    except (Warning, TypeError, KeyError, IndexError) as exc:
        raise ValueError(f'Invalid FITS: {exc}') from exc


def _validate_file(path):
    compressed = path.read_bytes()
    remaining, pieces, total = compressed, [], 0
    while remaining:
        decoder = bz2.BZ2Decompressor()
        decoded = decoder.decompress(remaining, max_length=268435457 - total)
        total += len(decoded)
        if total > 268435456 or not decoder.eof:
            raise ValueError('Truncated bz2 or uncompressed file exceeds 256 MiB')
        pieces.append(decoded)
        remaining = decoder.unused_data
    raw = b''.join(pieces)
    if not raw or len(raw) % 2880:
        raise ValueError('FITS length is not a complete number of 2880-byte blocks')
    shapes = []
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        with fits.open(io.BytesIO(raw), memmap=False, do_not_scale_image_data=True,
                       lazy_load_hdus=False) as hdus:
            hdus.verify('exception')
            for hdu in hdus:
                info = hdu.fileinfo()
                if info['datLoc'] + info['datSpan'] > len(raw):
                    raise ValueError('Truncated FITS data')
                if hdu.data is not None:
                    shapes.append(list(hdu.data.shape))
                for key, method in [('CHECKSUM', hdu.verify_checksum), ('DATASUM', hdu.verify_datasum)]:
                    if key in hdu.header and method() != 1:
                        raise ValueError(f'Invalid FITS {key}')
            if not shapes:
                raise ValueError('FITS contains no image/data array')
    return dict(compressed_bytes=len(compressed), sha256=hashlib.sha256(compressed).hexdigest(),
                fits_sha256=hashlib.sha256(raw).hexdigest(), shapes=shapes), raw


def coverage(rows, night):
    exposures = sorted((parse_utc(r['utc_start']), parse_utc(r['utc_end']))
                       for r in rows if r['eligible'] == 'true')
    cursor = parse_utc(night['dark_start_utc'])
    gaps = []
    for start, end in exposures:
        if start > cursor:
            gaps.append(dict(start_utc=utc_text(cursor), end_utc=utc_text(start),
                             seconds=(start - cursor).total_seconds()))
        cursor = max(cursor, end)
    end = parse_utc(night['dark_end_utc'])
    if cursor < end:
        gaps.append(dict(start_utc=utc_text(cursor), end_utc=utc_text(end), seconds=(end - cursor).total_seconds()))
    return gaps


def parallel_results(function, items, workers):
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        yield from pool.map(function, items)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def verify_timing(raw, row):
    actual = exposure_metadata(fits.Header.fromfile(io.BytesIO(raw)), row['filename'])
    for key in ('utc_start', 'utc_end', 'exposure_seconds'):
        if actual[key] != row[key]:
            raise ValueError('File timing differs from inventory; refresh headers if the remote file changed')


def decompress_original(path, raw, info, min_free_bytes):
    target = path.with_suffix('')
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == info['fits_sha256']:
        return 'verified_existing'
    if shutil.disk_usage(path.parent).free < min_free_bytes + len(raw):
        raise OSError('Insufficient disk for optional decompression; original remains verified')
    part = target.with_name(target.name + '.part')
    try:
        part.write_bytes(raw)
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)
    return 'written_byte_identical'


def run(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    http = HTTP(args.timeout, args.retries, args.delay)
    astronomy = Astronomy()
    report = dict(status='searching', output=str(out), archive=args.base_url,
                  astropy_version=astropy.__version__, ephemeris='Astropy builtin ERFA',
                  site=dict(latitude_deg=LAT, longitude_deg=LON, elevation_m=ELEVATION,
                            elevation_source='MMTO published summit elevation; camera height not surveyed'),
                  convention='Sun center geometric < -18 deg. Moon topocentric upper limb + 34 arcmin refraction + sea-horizon dip < 0; no terrain masking.',
                  search=[], listing_errors=[])
    atomic_json(out / 'report.json', report)
    root_html = http.text(args.base_url)
    (out / 'archive-index.html').write_text(root_html)
    links = Links()
    links.feed(root_html)
    available = {h.rstrip('/') for h in links.hrefs if re.fullmatch(r'\d{4}-\d{2}-\d{2}/?', h)}
    dates = [args.start_date + timedelta(days=i)
             for i in range((args.end_date - args.start_date).days + 1)]
    dates.sort(key=lambda d: (abs((d - args.near).days), d))
    rows, selected = [], None
    for day in dates:
        night = astronomy.night(day)
        report['search'].append(night)
        print(f"Night {day}: {night['reason']}", flush=True)
        atomic_json(out / 'report.json', report)
        if not night['qualifies']:
            continue
        wanted = archive_dates(night['dark_start_utc'], night['dark_end_utc'])
        if any(str(d) not in available for d in wanted):
            night['archive_status'] = 'missing_directory'
            continue
        trial = []
        for d in wanted:
            url = urljoin(args.base_url, f'{d}/')
            try:
                html = http.text(url)
                (out / f'listing-{d}.html').write_text(html)
                trial.extend(fits_links(html, url))
            except RuntimeError as exc:
                report['listing_errors'].append(str(exc))
                atomic_json(out / 'report.json', report)
                raise  # A failed listing must not become an apparently empty directory.
        if not trial:
            night['archive_status'] = 'no_fits_files'
            continue
        rows, selected = trial, night
        break
    if selected is None:
        report['status'] = 'no_qualifying_archived_night_in_range'
        atomic_json(out / 'report.json', report)
        print('No complete moonless archived night in range; broaden --start-date / --end-date.', file=sys.stderr)
        return 2
    report['selected'] = selected
    write_csv(out / 'moon-track.csv', astronomy.track, list(astronomy.track[0]))
    report['listed_fits_files'] = len(rows)
    # A filename-based estimate is ONLY diagnostic; headers remain authoritative.
    dark_start = parse_utc(selected['dark_start_utc'])
    dark_end = parse_utc(selected['dark_end_utc'])
    midpoint = dark_start + (dark_end - dark_start) / 2
    candidates = []
    for row in rows:
        stamp = STAMP.match(row['filename'])
        if stamp:
            created = datetime.strptime(stamp[1], '%Y_%m_%d__%H_%M_%S').replace(tzinfo=LOCAL).astimezone(UTC)
            if dark_start < created < dark_end:
                candidates.append(row)
    report['filename_dark_interval_candidates_not_exposure_verified'] = len(candidates)
    report['cadence_minutes'] = args.cadence_minutes
    report['scope'] = 'one image per cadence interval' if args.cadence_minutes else 'all available qualifying exposures'
    sample_urls = None
    if args.cadence_minutes:
        # Filenames only propose sample members; FITS headers decide qualification.
        # This mode intentionally does not claim a complete exposure inventory.
        groups = {}
        step = args.cadence_minutes * 60
        for row in candidates:
            stamp = STAMP.match(row['filename'])
            t = datetime.strptime(stamp[1], '%Y_%m_%d__%H_%M_%S').replace(tzinfo=LOCAL).astimezone(UTC)
            slot = int((t - dark_start).total_seconds() // step)
            target = dark_start + timedelta(seconds=min((slot + .5) * step, (dark_end-dark_start).total_seconds() - 1))
            groups.setdefault(slot, []).append((abs((t-target).total_seconds()), row['source_url']))
        sample_urls = {min(group)[1] for group in groups.values()}
        report['requested_sample_files'] = len(sample_urls)
        report['empty_sample_intervals'] = [i for i in range(math.ceil((dark_end-dark_start).total_seconds()/step)) if i not in groups]
        for row in rows:
            if row['source_url'] not in sample_urls:
                row['download_status'] = 'not_sampled'
    if args.max_probes:
        # For a bounded diagnostic run inspect evenly spread night samples first.
        # The normal exhaustive inventory does not filter or reorder by filename.
        indices = np.linspace(0, max(0, len(candidates) - 1), min(args.max_probes, len(candidates)), dtype=int)
        priority = [candidates[i] for i in indices]
        urls = {r['source_url'] for r in priority}
        rows = priority + [r for r in rows if r['source_url'] not in urls]
    report['status'] = 'inventory_in_progress'
    atomic_json(out / 'report.json', report)
    write_csv(out / 'manifest.csv', rows)
    cache = out / 'headers'
    cache.mkdir(exist_ok=True)
    # Inventory ALL FITS headers in the relevant noon buckets. No filename cuts.
    def inspect_header(item):
        index, row = item
        key = hashlib.sha256(row['source_url'].encode()).hexdigest()
        cached = cache / (key + '.json')
        if sample_urls is not None and row['source_url'] not in sample_urls:
            return row
        if args.max_probes and index >= args.max_probes:
            row['error'] = 'Explicit --max-probes limit; header not inspected'
            return row
        try:
            record = None
            if cached.exists() and not args.refresh_headers:
                try:
                    record = json.loads(cached.read_text())
                    header = fits.Header.fromstring(record['header'])
                    size = record['remote_bytes']
                except (ValueError, KeyError, OSError):
                    record = None
            if record is None:
                header, size = http.header(row['source_url'])
                atomic_json(cached, dict(source_url=row['source_url'], remote_bytes=size,
                                         header=header.tostring()))
            row['remote_bytes'] = size
            row.update(exposure_metadata(header, row['filename']))
            row['validation_status'] = 'header_only_not_bz2_integrity'
        except (RuntimeError, ValueError, KeyError, OSError) as exc:
            row.update(download_status='header_failed', validation_status='failed', error=str(exc))
        return row
    try:
        for index, _ in enumerate(parallel_results(inspect_header, enumerate(rows), args.workers)):
            if index % 25 == 0:
                print(f'Headers {index + 1}/{len(rows)}', flush=True)
                write_csv(out / 'manifest.csv', rows)
    finally:
        astronomy.annotate(rows, selected)
        write_csv(out / 'manifest.csv', rows)
    eligible = [r for r in rows if r['eligible'] == 'true']
    report['available_qualifying_exposures_confirmed'] = len(eligible)
    report['unresolved_headers'] = sum(r['eligible'] == 'unknown' and r['download_status'] != 'not_sampled' for r in rows)
    report['unsampled_files'] = sum(r['download_status'] == 'not_sampled' for r in rows)
    report['required_compressed_bytes'] = sum(r.get('remote_bytes', 0) for r in eligible)
    gaps = coverage(rows, selected)
    write_csv(out / 'coverage-gaps.csv', gaps, ['start_utc', 'end_utc', 'seconds'])
    report['coverage'] = dict(gaps=len(gaps), max_gap_seconds=max((g['seconds'] for g in gaps), default=0),
                              uninterrupted=False if report['unresolved_headers'] else not gaps,
                              basis='Sampled eligible headers' if args.cadence_minutes else 'All eligible archive headers, including images not yet downloaded',
                              inventory_complete=report['unresolved_headers'] == 0 and not args.cadence_minutes)
    report['status'] = 'downloading'
    atomic_json(out / 'report.json', report)
    print(f"Eligible exposures: {len(eligible)}; unresolved: {report['unresolved_headers']}; "
          f"compressed bytes: {report['required_compressed_bytes']}", flush=True)
    downloaded_bytes = 0
    def download_row(row):
        nonlocal downloaded_bytes
        directory = out / 'originals' / row['archive_date']
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / row['filename']
        receipt = path.with_name(path.name + '.verified.json')
        row['local_path'] = str(path)
        try:
            info, raw = None, None
            if path.exists():
                try:
                    info, raw = validate_file(path)
                    if receipt.exists() and json.loads(receipt.read_text())['sha256'] != info['sha256']:
                        raise ValueError('Local file differs from prior verified SHA256')
                    verify_timing(raw, row)
                    row['download_status'] = 'verified_existing'
                except (ValueError, OSError, EOFError, KeyError):
                    info = None
            if info is None:
                reserve = max(row.get('remote_bytes', 0), 16 * 1024 ** 2)
                if shutil.disk_usage(out).free < args.min_free_mib * 1024 ** 2 + args.workers * reserve:
                    row.update(download_status='space_blocked', error='Insufficient free disk space')
                    return row
                if args.max_download_mib and downloaded_bytes + reserve > args.max_download_mib * 1024 ** 2:
                    row.update(download_status='budget_blocked', error='Explicit --max-download-mib limit')
                    return row
                info, raw = http.download(row['source_url'], path)
                downloaded_bytes += info['compressed_bytes']
                row['download_status'] = 'downloaded'
            verify_timing(raw, row)
            row.update({k: v for k, v in info.items() if k != 'shapes'})
            row.update(fits_shapes=json.dumps(info['shapes']), validation_status='bz2_and_fits_valid', error='')
            atomic_json(receipt, dict(source_url=row['source_url'], **info))
        except (RuntimeError, ValueError, OSError, EOFError, KeyError) as exc:
            row.update(download_status='failed', validation_status='failed', error=str(exc))
            return row
        if args.decompress:
            try:
                row['decompression_status'] = decompress_original(path, raw, info, args.min_free_mib * 1024 ** 2)
            except OSError as exc:
                row.update(decompression_status='failed', decompression_error=str(exc))
        return row
    try:
        # A byte-budget run is serial so the cap cannot be oversubscribed.
        workers = 1 if args.max_download_mib else args.workers
        for index, _ in enumerate(parallel_results(download_row, eligible, workers)):
            if index % 10 == 0:
                write_csv(out / 'manifest.csv', rows)
                print(f'Downloads processed {index + 1}/{len(eligible)}', flush=True)
    finally:
        write_csv(out / 'manifest.csv', rows)
        success = [r for r in eligible if r['validation_status'] == 'bz2_and_fits_valid']
        report['verified_downloads'] = len(success)
        report['verified_compressed_bytes'] = sum(r['compressed_bytes'] for r in success)
        report['failed_or_pending_eligible_downloads'] = len(eligible) - len(success)
        report['decompression_failures'] = sum(r.get('decompression_status') == 'failed' for r in eligible)
        complete = bool(eligible) and len(success) == len(eligible) and report['unresolved_headers'] == 0
        if args.cadence_minutes:
            complete = complete and len(success) == report['requested_sample_files'] and not report['empty_sample_intervals']
        report['status'] = ('requested_sample_verified' if args.cadence_minutes else 'all_available_qualifying_files_verified') if complete else 'incomplete'
        atomic_json(out / 'report.json', report)
    print(json.dumps({k: report[k] for k in ('status', 'selected', 'available_qualifying_exposures_confirmed',
                                            'unresolved_headers', 'verified_downloads',
                                            'verified_compressed_bytes', 'output')}, indent=2))
    return 0 if complete and not report['decompression_failures'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('mmt-downloads'))
    parser.add_argument('--start-date', type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument('--end-date', type=date.fromisoformat, default=date(2026, 3, 31))
    parser.add_argument('--near', type=date.fromisoformat, default=date(2026, 1, 15))
    parser.add_argument('--base-url', default=BASE, help='Archive root; HTTP may work where HTTPS is blocked')
    parser.add_argument('--interval-minutes', '--cadence-minutes', dest='cadence_minutes', type=float, default=10, help='One image per interval in minutes (default: 10); 0 downloads all')
    parser.add_argument('--workers', type=int, default=4, help='Concurrent transfers (1-8), globally rate limited')
    parser.add_argument('--timeout', type=float, default=45)
    parser.add_argument('--retries', type=int, default=3, help='Additional attempts after the first')
    parser.add_argument('--delay', type=float, default=.5, help='Minimum seconds between request starts')
    parser.add_argument('--decompress', action='store_true', help='Also save exact decompressed FITS bytes')
    parser.add_argument('--refresh-headers', action='store_true')
    parser.add_argument('--min-free-mib', type=float, default=256, help='Keep this much disk space free')
    parser.add_argument('--max-download-mib', type=float, default=0, help='0=unlimited; a cap yields incomplete status')
    parser.add_argument('--max-probes', type=int, default=0, help='Diagnostic only: cap header probes; 0=all')
    args = parser.parse_args()
    if args.end_date < args.start_date:
        parser.error('--end-date precedes --start-date')
    for key in ('timeout', 'delay', 'min_free_mib', 'max_download_mib', 'cadence_minutes'):
        value = getattr(args, key)
        if not math.isfinite(value) or value < 0 or (key == 'timeout' and value == 0):
            parser.error(f'Invalid --{key.replace("_", "-")}')
    if not 1 <= args.workers <= 8:
        parser.error('--workers must be between 1 and 8')
    if args.retries < 0 or args.max_probes < 0:
        parser.error('Retries and probe limit must be nonnegative')
    args.base_url = args.base_url.rstrip('/') + '/'
    try:
        return run(args)
    except KeyboardInterrupt:
        print('Interrupted. Manifest/checkpoints retained; rerun the same command.', file=sys.stderr)
        return 130
    except Exception as exc:
        print(f'FAILED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
