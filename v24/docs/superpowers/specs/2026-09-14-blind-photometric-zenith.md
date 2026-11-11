# Blind photometric zenith constraint

User clarified that site/time-derived airmasses defeat the intended blind solve.
Implement the recorded point-source method: optimise physical zenith by minimising
scatter in instrumental minus catalogue magnitudes after regression against trial
airmass. Extinction slope and zero point are nuisance parameters. Do not supply
site, timestamp, manifest location, filename date, physical zenith from astrometric
refraction, or a saved solution to this optimiser. Preserve proper-motion checkpoint
0833bee and all historical assets in the original checkout.

The fit consumes measured stellar rays and usable unsaturated photometry. Fix its
star membership before searching; penalise candidate zeniths with any selected star
below the validity altitude rather than dropping stars. Seed globally from ray
geometry, not a supplied location. Profile regression parameters at each candidate
zenith, use a fixed robust loss scale, and compare candidate residual objectives.
Fit an optional constrained quadratic radial response as a sensitivity check;
vignetting, colour and cloud effects must be reported as limitations. A finite
conditional covariance, positive extinction evidence, adequate sky/airmass coverage,
and agreement under the radial-response check are required to label a conditional
photometric zenith. Otherwise retain a provisional candidate with unresolved status.

Export the chosen/provisional zenith, candidate objective map, regression fit,
per-star airmasses, and explicit input/membership provenance. The default scientific
analysis must no longer obtain airmasses from metadata. Metadata-seeded planetary
searches remain available only as explicit metadata diagnostics, not part of the
blind default. Report the distinction from the separate astrometric-refraction
zenith. This photometric constraint estimates physical zenith within the saved
astrometric frame; it does not by itself supply site/time or become an independent
calendar epoch. It does not alter astrometric positions cosmetically or claim a
joint refraction-corrected astrometric solution that has not been fitted.

Tests must recover synthetic tilted zenith with unknown extinction/zero point,
identify zero extinction and poor coverage as unresolved, check radial-response
sensitivity, and prove that changing site/time metadata cannot affect photometric
results. Then run all tests, preserved demo and a fresh blind scientific example.
