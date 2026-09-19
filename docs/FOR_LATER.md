# For later

Deferred ideas; recording an item here does not change solver behaviour.

## Earliest allowed epoch for known photographic processes

Recorded 2026-09-15. Deferred proposal for `go4.sh`; not implemented.

Consider an explicit, user-supplied earliest-epoch setting for both stellar and
planetary epoch searches. Record the chosen bound and its justification in the
results as a declared input-collection assumption, separate from an inferred
exposure date. Keep the existing current-time upper bound. Leave legacy `go.sh`
unchanged.

Colour alone does not justify a post-1940 cutoff: experimental three-colour
photography dates to 1861, commercial Autochrome plates to 1907, and Kodachrome
multilayer colour film to 1935. A 1935 or later lower bound needs knowledge of the
input collection or photographic process. Do not infer it merely from RGB
channels: scans, colourised monochrome photographs and coloured annotations can
also produce RGB files. Do not derive the bound from hidden exposure metadata.

Historical references:
- [National Science and Media Museum: Autochrome history](https://blog.scienceandmediamuseum.org.uk/autochromes-the-dawn-of-colour-photography/)
- [Kodak: Exploring the Color Image](https://www.kodak.com/content/products-brochures/Film/Exploring-the-Color-Image.pdf)

## Native dynamic range, FITS input and a results index

Recorded 2026-09-16. The native-depth/FITS portion was implemented in v6 on
2026-09-16. Automatic append-only SQLite storage is now implemented in the
working v6 version; see `v6/docs/DATABASE.md`. Repeated-star extraction and
duplicate elimination remain later analysis tasks.

V6 now uses one native loader for detection, photometry, planet evidence,
diagnostics and FITS export. It supports high-bit PNG/TIFF and 2-D, RGB and
`R/G1/G2/B` FITS stacks, masks invalid samples, records scaling/channel/
saturation provenance and keeps 8-bit stretches display-only. Tests cover
samples above 255, representative 12/14/16-bit gains, stacked-plane semantics,
centroid invariance, flux scaling and native-plane FITS round trips. RAW/Bayer
demosaicing remains outside the solver; users should convert those files into
rendered planes first.

Keep immutable per-run JSON/CSV/FITS products as the canonical evidence. For
cross-run work, add a rebuildable local SQLite index rather than making a
database the sole record. Index image hashes and pixel provenance, run/code and
catalogue versions, detections, catalogue associations, background-subtracted
aperture counts, exposure-normalized count rates, instrumental magnitudes,
planet candidates and separately labelled metadata. Use `count rate` for ADU/s;
do not call it physical flux. Planet and minor-planet identity rows should store
their measured per-channel instrumental magnitudes when the run is created, with
saturation/usability flags. Keep predicted apparent magnitudes separately
labelled, and do not make later database extraction recalculate routine stored
measurements.

During the present trial phase, continue retaining every run, including repeated
analyses of the same images. Later add an explicit database-maintenance command
that can preview and then remove exact duplicate runs and user-selected junk or
failed trials. It must default to a dry run, state the selection rule and affected
run IDs, and never infer that a scientifically different rerun is junk merely
because the input image hash repeats. Preserve or archive the immutable per-run
evidence so the SQLite index remains rebuildable and cleanup cannot silently
alter the solver's scientific record.

Cached identities or earlier solutions must never seed a blind solve, and
metadata revealed after fitting must remain distinguishable from values actually
used by a fit.

## High-dynamic-range all-sky archives and sparse trials

Recorded 2026-09-17. Keep source FITS local; commit only query metadata,
checksums and provenance. Dates and sites may be used only after a blind fit is
fixed, never to seed astrometry, airmass, zenith or epoch inference.

### Subaru Zenodo 3736793

Peter Thejll's Zenodo record <https://doi.org/10.5281/zenodo.3736793> is the
durable high-dynamic-range Subaru/Maunakea source. The camera can acquire
14-bit samples; the published dark-subtracted trial products are 488 x 652
floating-point FITS (`BITPIX=-64`). Storage type is not acquisition precision.
The public API listed 51 R and 8 G files on 2026-09-17, but no B file despite
the record description mentioning R/G/B.

Three checksum-verified trial files are recorded under
`data/zenodo-3736793/trial/README.md`. The matched-JD 16-second pair solved
blindly with go6: R yielded 159 candidates, 40 Gaia fits and 1.6800 px RMS;
G yielded 138 candidates, 46 Gaia fits and 1.7989 px RMS. The second R frame
was downloaded but not run. Keep the FITS themselves out of Git.

### ESO APICAM

APICAM means ApiCam-3 at Paranal, not the La Silla LASC camera. The combined
ESO La Silla Paranal archive name can obscure that distinction. ESO's raw API
returned no records for instrument `LASC`; its live-image system is separate.

The trial dataset `APICAM.2018-03-01T00:13:02.000` is a 120-second tracked
luminance exposure: one 4096 x 4096 unsigned-16 FITS image (`BITPIX=16`,
`BZERO=32768`), 33,557,760 bytes, SHA-256
`9d65d31113e85b8aa691d503800fbc33b45f025746d7e8012c9b93aad8a63de8`.
It has 58,621 pixels (0.3494%) at 65535 and no authoritative `SATURATE`
keyword. Its 1/50/99 percentiles are 620/3868/34193.85 ADU. Astropy inspection
must use `memmap=False` because scaled unsigned FITS cannot be memory-mapped.

Direct ESO counts on 2026-09-17 found 118,717 APICAM records from 2018-03-01
through 2020-06-25: 50,817 in 2018, 52,643 in 2019 and 15,257 in 2020.
The first ten records have a median 147-second cadence. At the trial size, a
complete uncompressed download is about 3.98 TB (3.62 TiB). For comparison,
the same API reported 326,523 ALPACA and 2,477,763 MASCOT records; never start
an unrestricted download of any of these collections.

Select metadata first, then download a scientifically designed subset. One
APICAM frame per calendar night is bounded by about 847 files/28 GB; a uniform
30-minute sample across every available sequence is roughly 9,900 files/330 GB.
Start instead with a few well-covered nights and 20--30 minute spacing across
airmass, inspect go6 success and saturation, then expand only if justified.
Keep `query_results.csv` beside each local trial and retain dataset IDs, dates,
checksums, exposure/filter metadata and the exact selection rule.

### Full-colour high-dynamic-range fisheye cameras

Recorded 2026-09-17. Find one or more fisheye/all-sky cameras that preserve
independent full-colour channels in a high-dynamic-range scientific format
(preferably linear multi-plane FITS or high-bit TIFF/PNG with documented channel
response). APICAM supplies high-dynamic-range luminance FITS, not colour; the
Subaru web-camera sample supplies colour only as processed 8-bit JPEG. Require
documented bit depth, linearity or transfer function, saturation behaviour,
channel layout/passbands and enough repeated exposures for colour/extinction
tests before treating such an archive as a calibration dataset.

The downloaded APICAM trial has now been run through the development launcher
and its repeated luminance photometry is analysed separately from colour data.
Do not fold exposure timestamps or the known Paranal site into the blind fit.
