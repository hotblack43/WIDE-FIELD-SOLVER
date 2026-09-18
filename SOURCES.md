# Raw colour all-sky source audit

Updated 2026-09-19. A source is marked **SUCCESS** only when an original file
was downloaded, decoded, and numerically inspected. The machine-readable
inspection record is `raw_allsky_samples/inspection.json`; originals are kept
unchanged beneath `raw_allsky_samples/`.

| Camera/site | Result | Public source | Inspected format and dimensions | Stored data | Colour layout | Stars | Sample |
|---|---|---|---|---|---|---|---|
| MMTO all-sky camera | **SUCCESS** | [archive](https://skycam.mmto.arizona.edu/skycam/archive/) | BZIP2-compressed FITS, `(3, 1411, 1422)` | `BITPIX=16`, 15-bit camera values, observed 1503–32767 in the recent sample | Three stored colour planes; header also records `BAYERIND=4` | Clear point stars in both samples | Yes, two |
| Rubin Observatory ASC | **SUCCESS (public sample only)** | [public CR2](https://drive.usercontent.google.com/download?id=1rk3PsfuUj_9HG8YBR8T2doCgGvOYnBkr&export=download&confirm=t) | Canon CR2, visible sensor `(4502, 6744)` | `uint16`, 14-bit, 1988–16383, black about 2049–2050 | Undemosaiced RGGB Bayer | Excellent point stars and Milky Way | Yes, one |
| TREx-RGB Gillam and Lucky Lake | **UNSUITABLE** | [dataset](https://data.phys.ucalgary.ca/data/datasets/trex_rgb.html) | HDF5 `/data/images`, `(480, 553, 3, 20)` | `uint8`; Gillam 0–210, Lucky Lake 2–247 | Three RGB channels, 20 frames | Lucky Lake has point stars; Gillam sample is bright/cloudy | Yes, two sites |
| PRESENTE / GOA-SCAN | **ACCESS RESTRICTED** | [live site](https://allsky.opt.cie.uva.es/) | Published design: HDF5, 2000×2000 | Sony IMX178, approximately 14-bit values in 16-bit arrays | Undemosaiced RGGB Bayer | System is intended for nocturnal sky monitoring | No public raw URL found |
| OASI | **RAW NOT FOUND** | [camera page](https://oasi.org.uk/Telescopes/allsky/allsky.php) | Historical page says FITS; reachable products found were JPEG/PNG/video | Not verifiable without an original | ZWO ASI178MC colour camera was documented | Rendered products show sky | No |
| Public INDI-AllSky installations | **RAW NOT FOUND** | [software](https://github.com/aaronwmorris/indi-allsky) | Software can retain 16-bit FITS, but five checked public viewers exposed no FITS/raw object | Public APIs returned null raw/FITS fields | Depends on installation | JPEG displays often show stars | No |

## MMTO

The dated public raw archive continues beyond the previously suspected
2026-06-23 endpoint. Direct directory listings were verified through at least
**2026-09-18**. The adapter understands the archive's Arizona local timestamps
and noon-to-noon directory buckets, so cadence selection happens from filenames
and listings before any FITS body is downloaded.

Inspected originals:

- `2026_03_15__00_00_18.fits.bz2`, 6,105,484 bytes, SHA-256
  `61b9883c184101bb5210b1d7efb17e3a3c4c6ff3a517371442e412d37949823e`.
  Source: <https://skycam.mmto.arizona.edu/skycam/archive/2026-03-15/2026_03_15__00_00_18.fits.bz2>
- `2026_09_18__00_00_13.fits.bz2`, 6,111,948 bytes, SHA-256
  `d102dbc8d9062bea57c32b4971e94d96b2b40e78990eadbbffe8a6f925217d90`.
  Source: <https://skycam.mmto.arizona.edu/skycam/archive/2026-09-18/2026_09_18__00_00_13.fits.bz2>

Both contain one primary image HDU with `BITPIX=16`, shape
`(3, 1411, 1422)`, `BITCAMPX=15`, `EXPOSURE=20.0`, and the instrument
`ZWO ASI294MC Pro`. The March file spans 1535–32767 with 12,263 distinct
values; the September file spans 1503–32767 with 12,040 distinct values. Their
saturation fractions at 32767 are approximately 0.0124% and 0.0096%. The
`DATAMAX` header is not the sensor clipping ceiling; inspection correctly uses
`BITCAMPX` for that purpose.

The FITS `DATE-OBS` clock is Arizona local time while `DATE` is UTC creation
time. The downloader retains both the raw timestamp and its verified UTC
interpretation. No explicit public reuse licence was located.

## Rubin Observatory

The verified file is `asc2506240487.cr2`, 28,412,776 bytes, SHA-256
`ab36ba13f71f19d10ca6c0b4597abd6efbfc46f8dd77802be9bb17711eceed2d`.
It is available from a [small public teaching folder](https://drive.google.com/drive/folders/1eLiKl3Dz8b7w3err5kIUVHFWQP9D_ySK?usp=sharing).
The downloader preserves the CR2 and uses its exact public file identifier.

`rawpy` inspected the genuine sensor mosaic, not the embedded JPEG. The visible
array is `(4502, 6744)` `uint16`, RGGB, with black levels
`[2049, 2050, 2050, 2049]`, a raw white level of 16383, values 1988–16383,
and 1,744 distinct values. Metadata give 30 s, ISO 400, f/4, 10 mm, and
`2025-06-25T04:06:01Z`. The original is a 14-bit high-dynamic-range Bayer
exposure with excellent point stars.

The [Rubin access notes](https://harvardwiki.atlassian.net/wiki/spaces/hufasstubbsgroup/pages/47454153/Rubin+All-sky+camera+data+and+access)
and [technical note](https://smtn-005.lsst.io/) describe the larger collection,
but continuing originals are on credentialed Rubin/USDF storage. Therefore the
public sample is a valid **SUCCESS**, while a public 20-minute Rubin cron feed
is not currently available. The cron wrapper fails closed rather than silently
substituting JPEGs. No explicit reuse licence was located for the teaching
sample.

## TREx-RGB

Two official `TREX_RGB_RAW_NOMINAL` minute bundles were downloaded:

- Gillam `20260115_0600_gill_rgb-04_full.h5`, 7,891,561 bytes, SHA-256
  `069e202a13461af56259106a90abf360e812bc64198d539f17c58adac6baa900`.
- Lucky Lake `20260115_0600_luck_rgb-03_full.h5`, 6,487,988 bytes, SHA-256
  `8afe703a9c3ba56cf644d6d2370c05ec887483e9c32c3a721e1e17ef70b7db73`.

The source URLs are respectively:

- <https://data.phys.ucalgary.ca/sort_by_project/TREx/RGB/stream0/2026/01/15/gill_rgb-04/ut06/20260115_0600_gill_rgb-04_full.h5>
- <https://data.phys.ucalgary.ca/sort_by_project/TREx/RGB/stream0/2026/01/15/luck_rgb-03/ut06/20260115_0600_luck_rgb-03_full.h5>

The HDF5 inspector recursively recorded `/data/images`, `/data/timestamp`,
`/metadata/file`, and all 20 `/metadata/frame/frameN` datasets. Images are
stored as `(480, 553, 3, 20)` `uint8` RGB. Frame metadata report roughly
2.56–2.88 s effective integrations, normally eight or nine averaged subframes,
and UTC timestamps at about three-second intervals. The numeric inspection is
decisive: this public nominal raw product does not preserve more than 8 bits,
so it is **UNSUITABLE** for the requested HDR dataset. HDF5 support remains in
the isolated inspector because it is required to establish this result and for
future suitable HDF5 sources.

## PRESENTE / GOA-SCAN

Published descriptions establish suitable source data: Sony IMX178 colour
sensors, undemosaiced RGGB values at approximately 14-bit depth stored in
16-bit HDF5 arrays. The [public live site](https://allsky.opt.cie.uva.es/)
serves rendered JPEG products; no legitimate public HDF5 listing or file URL
was found. This is not a download success. Raw access should be requested from
the [GOA contact](https://goa.uva.es/contact/) (`angel@goa.uva.es`). Licensing
and redistribution terms remain unknown.

## OASI

The project page documents an ASI178MC/fisheye system and historical FITS
acquisition. Searches of the reachable current and historical pages found only
rendered JPEG, PNG, and video products, not an original FITS exposure. Status is
therefore **RAW NOT FOUND**, not SUCCESS.

## Public INDI-AllSky installations

INDI-AllSky supports optional high-bit-depth FITS retention, but public display
pages commonly publish only rendered products. The public image-viewer APIs of
these independent installations were checked:

- <https://allskycam.star-astro.com/indi-allsky/imageviewer>
- <https://picam.patrickpapesch.at/indi-allsky/imageviewer>
- <https://skyimages.ddnss.eu/indi-allsky/imageviewer>
- <https://indi-allsky.dekorbaratok.hu/indi-allsky/imageviewer>
- <https://allsky.eyera.info/indi-allsky/imageviewer>

Each returned JPEG/panorama information with null FITS/raw fields. No
authentication was bypassed and no private paths were probed. These sites are
classified **RAW NOT FOUND**; licensing varies by operator.

## Inspection limits

Preview PNGs are derived visual checks and never replace the originals. Exact
array statistics and recursively captured metadata are in
`raw_allsky_samples/inspection.json`. Moon-down and solar-altitude selection are
not yet implemented, but site coordinates and timezone-aware observation times
are retained for that later work.
