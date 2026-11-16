# Paranal ApiCam v7 evidence

This note records the September 2026 v7 investigation of ESO Paranal ApiCam
images. It is regression evidence for the general blind stellar solver, not an
instrument-specific calibration or a saved solution used by the runtime.

## Instrument and input

ESO describes ApiCam-3 as a tracking camera using a 4096 by 4096 KAF-16803 CCD
and a Canon 12 mm fisheye lens. The published field is 180 degrees in diameter
at approximately 160 arcseconds per pixel:

<https://www.eso.org/cms/eso-archive-news/APICAM-all-sky-images-from-Paranal-available-in-the-Archive.html>

The principal trial was:

```text
eso_downloads/trial/APICAM.2018-09-16T00:13:55.000.fits
SHA-256 1a1a5923d5e2b1723450cc28ad1cdb1af2ce106d5b69e9d098415236ec7e02cb
```

Its FITS headers identify a 4096 by 4096, 16-bit KAF-16803 exposure through
`Fisheye-1`; `DATE-OBS`, `MJD-OBS`, `JD`, and the filename agree on
2018-09-16 00:13:55 UTC. The solver reads these time values only after blind
stellar astrometry, refraction, and photometric-zenith analysis have been fixed.

## Failure and correction

The original run detected 8,777 sources but stopped the blind bootstrap at the
first formally valid tetra3 result. That seed associated only 15 stars and, after
seed refinement, had 2.415-pixel or 6.252-arcminute RMS. It led to a poor lens
solution and a false association between Jupiter and a faint source.

The bootstrap now calculates exact great-circle residuals for every usable seed.
A seed at or below 3 arcminutes RMS is accepted immediately. A looser seed is
retained as a fallback while the remaining image patches and the existing
zero-distortion hypotheses continue. If no strong seed is found, the best weak
seed is still available, preserving the former ability to solve difficult
images.

For this image, the 15-star result is recorded as
`retained_weak_candidate`. A later zero-distortion trial finds 23 stars at
0.098 pixel or 0.251 arcminute RMS and is recorded as
`accepted_strong_candidate`. The decision uses only measured pixels and
catalogue geometry; no time, site, instrument identity, or saved camera enters
the bootstrap.

## Corrected normal run

The ordinary command is:

```sh
./go7.sh "eso_downloads/trial/APICAM.2018-09-16T00:13:55.000.fits"
```

The verified evidence run is retained locally under
`results/runs/APICAM.2018-09-16T00_13_55.000-v0.7.0-20260917T123655Z-TotgVT/`.
Its normal three-page report records:

- 8,032 stellar associations from 8,777 detections;
- 1.912 arcminute RMS, 1.413 arcminute median, and 2.975 arcminute 90th
  percentile residual;
- corresponding detector residuals of 0.702, 0.546, and 1.066 pixels;
- an 8.1-arcminute final association gate, with 97.2 percent of associations
  inside half that gate; and
- a fitted central scale of 2.5545 arcminutes per pixel, or 153.27 arcseconds
  per pixel, consistent with the approximate published value.

The fitted lens centre and zenith projection are close to the detector centre,
and the solution is mirrored. The camera parameters are consistent with the
adjacent 00:03:43 frame, which independently produced 8,549 associations at
1.895 arcminutes RMS. These results show that the sensor sampling and fisheye
lens are supported; the earlier failure was bootstrap selection, not a need for
an ApiCam-specific camera model.

## Planet result and limitation

The default post-fit planet stage selected the mutually agreeing FITS
`DATE-OBS` value and restricted the complete planet analysis to plus or minus
one day. It recovered the three bright saturated objects:

| Planet | Detection | Residual (pixel) | Flux above background (ADU) |
|---|---:|---:|---:|
| Mars | 2 | 0.948 | 3,243,638 |
| Jupiter | 3 | 0.335 | 2,121,776 |
| Saturn | 7 | 0.454 | 1,044,802 |

The locally fitted epoch is 2018-09-15 23:07:46.381 TDB, 4,037.8 seconds before
the metadata time, with a conditional positional uncertainty of 148.4 minutes.
The metadata time is therefore compatible with the positional result, but this
does not establish a precise blind epoch. Products label the result
`metadata_conditioned` and preserve the timing offset. `--blind-planets` still
forces the full 1850-to-run-time search; an image without usable time metadata
automatically takes the same blind fallback.

## Regression coverage

The tests cover FITS, EXIF, filename, and explicit-time precedence; metadata
conflicts and malformed values; the blind override and no-metadata fallback;
angular association, rotationally invariant robust fitting, diagnostics and
reports; and the weak-seed/strong-fallback bootstrap sequence. Before publication
the required full v7 suite, demo regression, launcher tests, preserved-version
hash checks, manifest checks, and whitespace validation must all pass on the
tree being committed.
