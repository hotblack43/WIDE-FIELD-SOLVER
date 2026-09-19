# MMTO database inspection

Run `./go_plot_things_1.sh` from any directory. It regenerates
`results/inspection/inspection.pdf` and matching PNG/CSV/JSON products.
The default PDF contains four pages:

1. R versus Gaia RP, G versus Gaia G, B versus Gaia BP (three panels).
2. Lightcurves: four stars down the rows (two bright, two near Gaia G=5),
   with R, G and B across the columns.
3. Machine magnitude minus catalogue magnitude versus stored airmass, for the
   same four stars and RGB columns (R−RP, G−G, B−BP).
4. Three colour panels: machine B−G versus G−R (coloured by Gaia BP−RP),
   then machine B−G and G−R versus Gaia BP−RP (coloured by stored blind airmass).

The colour page uses all eligible stars with Gaia G <= 5.5, not just the selected
lightcurve stars. All three channels must pass the existing rate/saturation cuts
for the same detection, image, run and catalogue. Each point is one star in one
exposure; no nightly averaging, fits or extinction corrections are applied.
The two airmass-coloured panels share a logarithmic colour scale, with no upper
airmass cut. Colour plots and `colours.csv` require verified finite airmass >= 1.
Missing Gaia BP/RP or incomplete RGB pairs are excluded. `--colour-max-mag` changes the
faint limit. `colours.csv` exports the plotted pairs and their provenance, and
`summary.json` records pair/star counts. Colour axes are instrumental and do not
imply calibrated Gaia colours.

The original eight-star, single-channel pages remain available as
`lightcurves_R`, `lightcurves_G`, `lightcurves_B`, `airmass_R`, `airmass_G`,
and `airmass_B`. The compact pages are `lightcurves_RGB` and `airmass_RGB`;
they take the first two stars from each brightness group of that same selection.
`--plots all` includes every variant, so use the default for compact inspection.
All lightcurve and airmass pages retain consistent night colours.
The airmass pages use the saved blind image-solution airmass, requiring finite values >= 1
and verified blind provenance in `photometry_summary.json`. Missing or invalid
airmass/catalogue pairs are omitted only from these pages, with omission counts
in the affected panels. The vertical axis increases normally (larger magnitude
differences upwards); no fitted trend, residual clipping or upper airmass cut is
applied. Airmass provenance and magnitude differences are exported in the CSV.

Use `--catalogue-band G` to compare all three camera channels against Gaia G.
The passbands differ and no calibration or extinction correction is implied.
No solver or database write is invoked.

The time axis is hours since preceding MMTO local noon (America/Phoenix).
Different local-noon dates have consistent colours/markers on all pages.
Original FITS files must match the database SHA-256. The existing MMTO archive
clock validator checks the site and the relationship between local `DATE-OBS`,
exposure duration, and UTC `DATE`. The exposure midpoint is then used. Filenames
locate files but are not used as observation clocks. Missing/invalid original
files are listed in `summary.json`; use `--image-root` if originals have moved.

Only positive stored `*_count_rate_adu_per_s` is used, with a known unsaturated
channel, aperture measurement method, and an exposure matching the FITS header.
Machine magnitude is `-2.5 log10(stored ADU/s)`. Stored `*_mag` and raw counts are
never substituted. Each channel is checked independently; missing airmass does
not prevent a catalogue comparison or a lightcurve.

## Repeated solves and consistent reductions

The solver continues to append every attempt to SQLite. The MMTO extractor is
read-only and counts an image only once, using its SHA-256 rather than its path.
Renaming/moving an image does not create another observation. No database rows
are removed, rewritten or deduplicated in storage.

The default solver selection is **0.10.0**, not the latest version in the database.
Within that version, choose one configuration/catalogue group covering the most
distinct images; repeated solves do not increase coverage. Ties prefer the group
with the newest recorded run (run ID breaks timestamp ties), then the lexical
group key. The default group may
therefore change as the database grows: pin both hashes below when comparing a
fixed reduction over time. Never combine groups to fill gaps in a series.

Within the selected group, use the latest successful run per image **before**
quality cuts (recorded UTC time, with run ID breaking ties). A later failed solve
does not displace a successful one. A bad/missing channel in the selected run
does not resurrect measurements from an older run. Existing saturation,
exposure, FITS identity/time and blind-airmass checks still apply unchanged.

The configuration fingerprint covers the saved model, epoch mode, blindness
flags, explicit `configuration` object if present, code hashes and source-manifest
hashes. Fixed epochs and recorded search limits are distinguished. A search
ceiling explicitly recorded as the current system time is represented by that
policy, not its changing timestamp. Fitted epochs, residuals, image paths and run
durations are not configuration. Historical databases do not record the complete
CLI: this fingerprint distinguishes **recorded provenance**, not unknowable
historical settings. Runs missing image/catalogue identity, model/epoch mode or
code provenance are omitted and counted. Source-manifest grouping is conservative:
even a non-scientific manifest change can separate groups.

`--list-reductions` prints groups and the default selection without reading FITS,
rendering plots or changing the database. Use `--solver-version`,
`--config-sha256` and `--catalogue-sha256` for an explicit selection; unmatched
selections fail rather than falling back. The solver catalogue hash is separate
from `--catalogue`, the Gaia photometric comparison CSV.

`summary.json` includes the chosen group, exact selected run IDs, counts of
superseded/failed/other-version/other-group runs, available groups, and hashes of
the plotter and comparison CSV. Measurement CSV and image provenance entries
also record solver version, configuration hash and run recording time. Selected
run IDs include any images subsequently omitted by the existing quality checks;
their omission reasons remain in image provenance.

Sample selection uses G measurements, at least
3 distinct images, and at least 60% of the best coverage. Select four brightest
eligible stars, then four other stars nearest G=5. Insufficient coverage yields
fewer panels, never relaxed cuts. Display names use saved/cached exact aliases;
unnamed stars have numbered panel labels and retain IDs in the audit files.

```sh
./go_plot_things_1.sh --output results/my-mmto-plots
./go_plot_things_1.sh --list-reductions
./go_plot_things_1.sh --solver-version 0.10.0 --config-sha256 FULL_CONFIG_HASH --catalogue-sha256 FULL_CATALOGUE_HASH
./go_plot_things_1.sh --plots rgb_catalogue,lightcurves_G
./go_plot_things_1.sh --plots airmass_R,airmass_G,airmass_B
./go_plot_things_1.sh --plots colours --colour-max-mag 5.5
./go_plot_things_1.sh --plots lightcurves_RGB,airmass_RGB,colours
./go_plot_things_1.sh --min-points 6 --coverage 0.8 --target-mag 5.5
```

`PLOT_REGISTRY` in `scripts/plot_things_1.py` contains figure-producing functions
with signature `(rows, selected_stars, args)`. Add a registry entry to add a page.
`measurements.csv` records channel rates, magnitudes, UTC midpoints and local
times; `selected_stars.json` identifies the eight-star sample. `summary.json`
records accepted/rejected image provenance, counts and the current generated
files. Old PNGs from earlier versions may remain in an existing output folder;
they are not included in the PDF or the current generated-files list.
