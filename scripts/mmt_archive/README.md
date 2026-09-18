# MMT moonless-night downloader

Download one image every **10 minutes** from a complete moonless astronomical
night. Change the interval with `--interval-minutes`; use `0` for every available
qualifying exposure. Original `.fits.bz2` files and names are preserved.

## Ubuntu setup and run

These commands assume the three supplied files are in
`/dmidata/projects/earthshine/MMTO/downloader` (Ubuntu 24.04 / Python 3.12):

```bash
sudo apt update
sudo apt install -y python3 python3-venv
cd /dmidata/projects/earthshine/MMTO/downloader
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python download_mmt.py --output /dmidata/projects/earthshine/MMTO
```

Examples:

```bash
# Five-minute samples; date bounds are inclusive LOCAL observing dates.
python download_mmt.py --output /dmidata/projects/earthshine/MMTO-five-minute \
  --interval-minutes 5 --start-date 2026-01-14 --end-date 2026-02-28

# Every qualifying exposure, plus optional lossless decompression:
python download_mmt.py --output /dmidata/projects/earthshine/MMTO-full \
  --interval-minutes 0 --decompress

# Tests (no internet required):
python -m unittest discover -v
```

The default search spans 2026-01-01 through 2026-03-31, nearest 2026-01-15 first.
Set `--near`, `--start-date`, and `--end-date` to search elsewhere. No partially
moonless night is accepted. Rerun the same command to resume: existing originals
are rechecked for bz2/FITS integrity and their saved SHA256 before being skipped.
Use a separate output directory to retain separate manifests for different runs.

`--timeout 45`, `--retries 3`, `--workers 4`, and `--delay 0.5` bound requests,
retries, concurrency, and the global request-start rate. Failed transfers restart
from zero; completed verified files are reused. `--refresh-headers` refreshes the
header cache. Optional `--max-probes` and `--max-download-mib` are diagnostic caps
and cannot produce a full-download success when work remains.

## Output

- `originals/YYYY-MM-DD/`: original compressed files and SHA256 receipts.
- `manifest.csv`: every listed FITS URL, filename, raw and UTC exposure times,
  exposure length, Sun/Moon altitudes, eligibility, transfer/validation status.
  Unselected files explicitly say `not_sampled`; their timing is not verified.
- `report.json`: night selection, assumptions, exact counts, size, failures.
- `moon-track.csv`: whole-night topocentric Moon and Sun track.
- `coverage-gaps.csv`: gaps between the selected exposures, including boundaries.
- `headers/` and saved HTML listings: inspection/resume evidence.

Exit 0 means the requested sample (or all eligible files in interval-0 mode) was
verified; exit 2 means incomplete/failed; exit 130 means interrupted. Sampling
chooses the available filename nearest the middle of each interval, then checks
its actual FITS exposure start/end. Cadence is approximate because exposures are
not taken at exact ten-minute boundaries. Empty intervals and invalid candidates
remain explicit failures. Full mode reads **all** listed FITS headers in the
relevant archive buckets, including equivalent `.fit.bz2`/`.fts.bz2` extensions.
Downloading all archived files does not establish uninterrupted camera coverage.
Missing exposures absent from the listing cannot be named; gaps remain visible.

## Scientific and timestamp conventions

Sun: topocentric centre, geometric altitude below −18°, with both crossings
root-solved. Moon: topocentric centre plus its distance-dependent semidiameter,
34 arcminutes standard horizon refraction, and 1.642° geometric sea-horizon dip
at 2616 m. Require that sum below zero throughout darkness. Terrain obstruction
is ignored. This is deliberately stricter than a level astronomical horizon.
The 60-second grid includes endpoints; sign crossings and local maxima are
checked. A 0.01°/s angular-rate enclosure plus 0.02° ephemeris margin bounds the
unsampled intervals. Astropy's builtin ERFA ephemeris and bundled IERS data are
used. Actual weather refraction is not inferred from zero-valued header fields.
Whole exposures must lie strictly inside both twilight boundaries.

The inspected FITS headers give camera coordinates **31°41′12″ N,
110°53′03″ W**. The [observatory publishes a 2616 m summit elevation](https://www.mmto.org/the-story-of-the-observatory/).
That is the site-height approximation used here; a surveyed camera mounting
height was not found. The chosen night has over 7° conservative Moon clearance.

**Important archive timing anomaly:** two original samples from the
[2026-01-15 listing](https://skycam.mmto.arizona.edu/skycam/archive/2026-01-15/)
have `DATE-OBS`/`UT` labelled UT, but actually contain local Arizona clock time.
The adjacent archive JPEG `2026_01_15__12_00_03.jpg` explicitly prints
`LT 1/15/2026 11:59:57 AM` and shows daylight. Its neighbouring FITS has
`DATE-OBS=2026-01-15T12:00:14.853600`, `EXPOSURE=0.01895`, and
`DATE=2026-01-15T19:00:18.549000`. The midnight FITS similarly has
`DATE-OBS=2026-01-15T23:59:38.472000`, exposure 20 s, and
`DATE=2026-01-16T07:00:00.602500`. Thus this camera's `DATE-OBS` and filenames
use America/Phoenix (UTC−07); `DATE` is UTC creation. This conversion is checked
for every selected file; conflicting clocks fail closed. Raw headers are never
corrected or rewritten. Other camera configurations may need fresh inspection.

The [Skywatch manufacturer manual, section 3.2](https://www.alcor-system.com/common/allSky/docs/OMEA_Camera%20ALL%20SKY%20CAMERA_Doc.pdf)
documents **noon-to-noon** directories, confirmed by the actual listing. The
script maps the full UTC interval to those local buckets rather than assuming
UTC-date directories. This particular local night crosses local midnight but
lies entirely on January 17 UTC and within archive directory `2026-01-16`.
The observed primary FITS image is `(3, 1411, 1422)`, `BITPIX=16`. No plane,
colour, scaling, or pixel transformations are applied. `--decompress` writes
exact bz2-decoded bytes, preserving headers and padding as well as pixels.

## Completed run

Local observing date: **2026-01-16**. Astronomical darkness:
**2026-01-17 02:08:58.303–12:57:55.171 UTC**. No Moon-horizon crossings;
conservative upper-limb altitude bound relative to the dipped apparent horizon
**−7.184°**. January 15 fails this deliberately stricter horizon convention.

The user-requested ten-minute sample contains **65/65 verified images**, totaling
**400,817,367 bytes** (400.8 MB). No selected-file failures. Output:
`/dmidata/projects/earthshine/MMTO/originals/2026-01-16/`.
There are 4,008 FITS files in the whole noon-to-noon bucket and 1,433 filename-time
candidates during darkness; the latter is not a header-verified count of all
qualifying exposures. The delivered 65-image sample is not uninterrupted coverage
and does not claim to download every archive exposure.
