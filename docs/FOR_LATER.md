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
2026-09-16. The results index remains deferred.

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
catalogue versions, detections, catalogue associations, aperture fluxes,
instrumental magnitudes, planet candidates and separately labelled metadata.
Cached identities or earlier solutions must never seed a blind solve, and
metadata revealed after fitting must remain distinguishable from values actually
used by a fit.
