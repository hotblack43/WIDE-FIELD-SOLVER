# Blind planetary epoch implementation plan

Goal: restore planetary date inference without observation metadata, preserving v0.4.1.
Spec: GOAL.md, especially independent planetary epoch and blindness boundary.
Architecture: separate reference ephemerides, positional search, and report integration.
Default date interval is Julian years 1850–2150, independent of image metadata and
of the fitted stellar epoch. Search all seven existing planet species against
all measured detections, including broad/saturated sources. Associated stars
are competing explanations: require positional delta chi-square >=9 before
counting a catalogue-associated detection as a planet candidate. Do not supply
Saturn's identity or an expected date to the search. Keep competing planet/date
solutions, not just the numerical winner. No astrometric fitting change.

- [x] Reference ephemerides: point_star_planet_ephemeris.py, with PLANETS,
  planet_vectors(name, jd_tdb) returning (N,3) geocentric apparent directions,
  and load_ephemeris(start_jyear, end_jyear, cache_dir) returning jd_tdb,
  vectors dict, provenance. Pure reference cache local to repo; no image data.
  Test vector shape/norm, interpolation accuracy, cache validation, no network/site.
- [x] Search: point_star_planets.py, scan daily trajectory segments against
  measured rays, refine local minima, combine unique contemporaneous matches,
  preserve aliases and positional/local time uncertainty. Synthetic known-date,
  multiple dates, fast sub-day crossing, empty/false candidates, duplicate source
  assignments and metadata-poisoning tests must fail before implementation.
- [x] Integrate: normal analyse_existing calls blind search; preserve explicit
  legacy control. Record all candidates in JSON/CSV and plot measured candidates
  faithfully. Reports distinguish candidate date from established epoch and
  label ambiguous planet identities. Default search may return ambiguity.
- [x] Release v0.4.2: new worktree and versioned launcher; only go4.sh follows it.
  Keep go.sh and earlier versioned launchers untouched. Update feature status.
- [x] Validate: full unittest and preserved demo, new Warwick full run, compare
  astrometric products to v0.4.1; scientific/code review, commit and push.

Ephemeris convention: Astropy get_body(..., location=None, ephemeris='builtin')
uses geocentric apparent GCRS directions and includes light time. Mapping through
the catalogue-fitted camera is approximate; annual aberration/frame differences,
unmodelled refraction, ephemeris error and absent topocentric parallax must remain
explicit limitations of conditional date uncertainty. No claims of exact dates
from a single local minimum. Do not use UTC wall clock for candidate selection.

User added: print every candidate epoch, produce an epoch-versus-residual plot,
and add a report appendix page so existing figures retain their size.

Verification: 99 tests pass; historical demo: 3653 associations/RMS0.397892px.
Fresh Warwick run through go4.sh generated a 3-page PDF and 103 candidate epochs;
star_coordinates.csv, stellar_epoch.json, photometric_zenith.json and
stellar_photometry.csv are byte-identical to v0.4.1. Independent review approved
after fixing artificial boundary aliases; no expected date was selected.
