# V21 MMTO FITS-header time and post-fit products

V21 reprocesses the existing verified MMTO archive without copying the archive
or its databases. It appends `0.21.0` receipts to `results/stars.sqlite` and
stores immutable header interpretations in
`raw_allsky_samples/manifest.sqlite:mmto_v21_observations`.

## Timing rule

The scientific timestamp is the FITS exposure midpoint:

```text
midpoint_UTC = header_start_UTC + 0.5 * header_exposure_seconds
```

Old MMTO headers are accepted only when their Arizona-local `DATE-OBS`, `UT`
and UTC creation clock agree under the documented schema. New headers are
accepted only when `DATE-BEG`, `DATE-END`, exposure duration and local
`DATE-OBS` agree. The instrument, site coordinates and stack semantics are also
checked. Missing or contradictory fields stop processing. A filename timestamp
is never used.

The listing timestamp stays unchanged in the `downloads` table. The sidecar
records header start, midpoint, exposure, schema, provenance and instrument by
source checksum, so both meanings remain inspectable.

## Blind boundary

`go21.sh` receives the image and `--blind-planets`, but no observation time,
latitude or longitude. Star association, Barghini astrometry, refraction,
photometric zenith and planet candidates are therefore fixed before metadata is
revealed. Known MMTO coordinates are latitude `31.6866666667` degrees,
east-positive longitude `-110.8841666667` degrees and elevation `2616 m`.

The post-fit validator computes the known zenith, latitude residual, per-star
airmass, parallactic/refraction-toward-zenith direction and stellar-epoch
difference. It also lists the header-time offset of every saved blind planet
candidate. It never reranks or rewrites those candidates.

## Grey transparency

For each observing night and native colour channel, v21 fits

```text
m(s,i) = a_s + k X(s,i) + Z_i,   with sum_i Z_i = 0
```

using a fixed sample and soft-L1 residual loss. Here `a_s` absorbs each star's
stable instrumental/catalogue and colour offset, `k` is the common nightly
airmass coefficient, and `Z_i` is an exposure-wide grey transparency term.
Rank-deficient or airmass-confounded groups are reported rather than forced.
Corrected instrumental magnitude is `m_machine - k X - Z_i`.

## Same-sidereal transmission

Distinct observing nights are paired one-to-one at the closest apparent local
sidereal time within five minutes by default. Common stars are differenced per
channel after the v21 correction, and the pair median is removed to expose
spatially differential transmission. Output maps show the actual measured
first-exposure centroids; the second coordinates remain in the audit CSV. No
interpolation or cosmetic displacement is used. Pairs below the common-star
threshold are explicitly labelled insufficient.

## Main output files

- `nightly-extinction-v21/grey_transparency.png`
- `nightly-extinction-v21/image_grey_transparency.csv`
- `same-sidereal-transmission/maps/*.png`
- `same-sidereal-transmission/sidereal_pair_summary.csv`
- `known-site-time-validation/mmto_site_time_validation.png`
- `known-site-time-validation/mmto_planet_epoch_validation.png`
- `known-site-time-validation/mmto_site_time_validation.csv`
- `known-site-time-validation/mmto_planet_epoch_validation.csv`

The pipeline summary records every stage and its exit status. A separate
recent-night queue ensures that current and intervening newly available nights
are considered before old backlog. The durable backfill cursor and recent-night
queue advance only after selected images have v21 receipts.

## Verification on 2026-10-19

- The complete root suite ran 554 tests with no failures and one optional
  `h5py` skip; the v15 and v17 preservation checks passed.
- `./demo.sh --output results/check-unique-name` passed with 3,653 associations,
  0.397892-pixel RMS and no withheld stars.
- A real one-image `--dry-run` listed the current observing night, selected
  `2026_10_18__22_00_04.fits.bz2`, and performed no download, solve or state
  advance.

## Recent-night queue verification on 2026-10-20

- The complete root suite ran 557 tests with no failures and one optional
  `h5py` skip.
- `./demo.sh --output results/check-unique-name` passed with 3,653
  associations, 0.397892-pixel RMS and no withheld stars.
- A real 40-image dry run checked the current and two intervening observing
  nights, selected 39 recent unfinished images first, then filled the final
  slot with one older unfinished local image. It performed no download, solve
  or state advance.
