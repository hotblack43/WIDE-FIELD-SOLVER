# Early Sun/Moon horizon corroboration in v15

## Scientific role

The Moon is independent evidence about planet-date proposals. It is not added
to the point-source catalogue, the Barghini objective, the joint epoch fit, or
the saved coordinate solution. Its frequently saturated disk and halo make a
point-centroid treatment unnecessary and unsafe.

For each interpolated positional proposal, v15 combines that date with the already-fixed
image-derived zenith. Transforming the zenith into the Earth-fixed frame yields
an implied observer latitude and longitude without reading site or timestamp
metadata. Astropy's pinned builtin ephemeris then supplies an offline
topocentric apparent Moon direction. Only its altitude relative to the
image-derived horizon enters the gate. Observer height is unknowable from a
direction alone and is fixed to sea level.

The calculation is offline. It uses Astropy's bundled Earth-orientation table,
allows that pinned table beyond its predictive-age freshness check, and uses
Astropy's mean-polar-motion fallback outside the table. That approximation is
at arcsecond scale and is negligible beside the five-degree horizon guard.

## Evidence rules

The image is classified before evaluating dates. Every unidentified broad or
saturated detection has its minor-axis angular diameter calculated through the
fitted camera. It is a possible Moon only when its minor diameter is at least
0.5 degrees, its centre is at least 5 degrees above the derived horizon, and it
is saturated or has peak SNR at least 25. Thus small saturated stars and broad
low-significance detections are not Moon candidates.

The predicted state is `above_horizon` above +5 degrees, `below_horizon` below
-5 degrees, and unresolved inside that guard. A proposal is contradicted when:

- a bright resolved Moon-like object is observed but the Moon is predicted below; or
- no bright resolved Moon-like object is observed but the Moon is predicted above.

The phase, predicted detector position, masks, image edge and positional
coincidence do not enter this intentionally coarse gate. Horizon-guard and
ephemeris failures remain neutral.

## Candidate ranking and limits

The Sun and Moon decisions are combined immediately after the cheap
interpolated proposal. A contradiction prevents exact planet ephemeris
refinement and all later joint trials for that visit. Compatible proposals keep
the inherited planet search and ranking. The Moon cannot turn an ambiguous
planet search into a unique epoch claim.

The calculation uses no hidden observation site, timestamp, filename date,
saved identity or metadata-derived airmass. It does not model cloud physics,
lunar surface brightness, camera blooming, atmospheric refraction of the Moon,
or observatory height. Brightness and size thresholds are deliberately
conservative operational criteria, not lunar photometry.

## Outputs

- `planet_search_performance.json`: number of visits rejected before exact refinement and exact-call timing;
- `celestial_gate_rejections.json`: every rejected proposal date, source,
  refinement/positional bracket, and complete Sun/Moon assessment;
- `celestial_gate_rejections.csv`: flat investigator-facing index of those
  rejected proposals, including separate solar and lunar causes;
- `lunar_evidence.json`: image-level Moon classification plus retained-candidate horizon audit;
- `planet_candidates.csv`: retained-candidate lunar status and predicted altitude;
- `report.pdf`: a plain-language summary of dates rejected by the Moon constraint.

Regression coverage includes topocentric parallax, derived observer location,
angular-size and luminance rejection, binary presence/absence, phase neutrality,
early rejection before exact planet ephemerides, pipeline integration and report
rendering.

## Measured v14-to-v15 performance

The recorded comparison uses the same MMTO FITS image (SHA-256
`6024db5eca256e1a6cdf9f33aa75ff48722f82bed77127a67aff50e59fa5d6e1`),
the full blind 1850-to-present planet search, the packaged Gaia catalogue,
and four planet workers in both versions. The launchers were invoked as
`./go14.sh IMAGE --blind-planets` and
`/usr/bin/time -p ./go15.sh IMAGE --blind-planets --results-dir RESULTS`.
The v14 and v15 telemetry reported 215.994 and 30.287 seconds respectively
for the complete planet stage: a 7.132-fold speedup (85.98% reduction).
Exact ephemeris dates fell from 172,704 to 21,439; v15 rejected 881 of 982
positional visits before exact refinement. Full-run wall time changed from an
inferred 372.69 seconds in v14 to a measured 341.17 seconds in v15 (8.46%
reduction). The planet-stage telemetry is the cleaner comparison because the
v14 full-run time is inferred from timestamps and another v14 queue process
was active during the v15 run. Machine-readable provenance and values are in
[`V14_V15_PERFORMANCE_BENCHMARK.json`](V14_V15_PERFORMANCE_BENCHMARK.json).
