# FITS image, ZPN coordinates and selectable DS9 overlays

`go5.sh` writes two FITS products after the scientific fits are fixed:

- `solution.fits` is a conventional two-dimensional primary image with the
  validated ZPN WCS. It is intended for Astrometry.net `solve-field` and other
  FITS programs that read only the primary HDU.
- `solution_annotated.fits` preserves the full decoded monochrome/RGB pixels
  and embeds the selectable annotations and solver evidence for the supplied
  viewer.

No stars are refitted and image geometry is not resampled. RGB pixels are
converted to luminance only in the compatible `solution.fits`; the annotated
file retains all three original channels. Legacy `go.sh` and its dependencies
are unchanged.

## Open the image with full overlays

From the repository:

```sh
./v5/view_fits.sh /path/to/analysis/solution_annotated.fits
```

In DS9, use **Region → Show** to switch the overlays off/on and **Region → Show
Text** to control the labels. The image and its cursor coordinates remain
available with the overlays hidden. Regions are tagged as `star`,
`matched_planet`, `predicted_planet` and `zenith` for selection through DS9 groups.
Ambiguous matches are labelled “candidate”; the DS9 window title gives the
planet-epoch status and candidate epoch, also retained in the FITS. Only the best candidate is drawn.

The viewer reads the annotations from this FITS and temporarily extracts a DS9
region file. There is no permanent companion `.reg` file to keep or copy. The
helper requires the repository's Python environment and DS9 on PATH. It starts
DS9 only when explicitly invoked; ordinary solving does not open viewer windows.

**Opening the FITS directly in DS9 has less functionality.** DS9 8.5's native
FITS-region importer loads basic shapes, but ignores label text and per-object
colours and line widths. Its normal FITS loader can autoload `REGION` when
“Autoload FITS regions” is enabled; the RGB-image loader does not use that same
autoload path. Use the helper for full, consistent mono/RGB overlays.

## File contents

`solution.fits` has exactly one two-dimensional primary HDU. Monochrome input
pixels are retained; RGB input uses rounded Rec. 709 luminance. The primary
header contains the ZPN WCS and records whether the pixels are original mono or
derived luminance. There are no annotation extensions in this compatibility
product.

`solution_annotated.fits` contains:

- Monochrome input in the primary HDU, or an empty primary followed by `RED`,
  `GREEN`, `BLUE` image extensions for RGB input. Each image has the same WCS;
  pixel values and original row order are preserved.
- `REGION`: basic shapes in a FITS binary table, with one-based pixel positions.
- `DS9TEXT`: UTF-8 bytes of styled DS9 regions, including labels and leader lines.
- `WFSINFO`: UTF-8 JSON containing the fixed camera, overlay positions,
  candidate status/epoch, label layout, product names and WCS validation evidence.

The old single-file RGB layout placed no image in the primary HDU. Astrometry.net
0.93 consequently stopped at `NAXIS = 0` unless explicitly told to read the
`RED` extension. The annotation tables were not the cause. The new plain file
works with the ordinary command:

```sh
solve-field /path/to/analysis/solution.fits
```

The helper applies DS9's display-only Y flip so the image looks upright like the
input JPEG/PNG. It does not change pixels or coordinates. Planet markers are
unfilled stars: width 2 for measured matches and width 1 for predictions at the
same candidate epoch. The saved photometric zenith is separately labelled with
its conditional/provisional status. Label placement avoids occupied boxes and
source markers at a 700-pixel initial displayed image size; the helper establishes that zoom explicitly and uses a fixed pixel font size. No marker is moved. DS9 does not
reflow text when the window size or zoom changes, so extreme zoom-out can still
produce overlap. This does not change the PDF's existing label placement.

## Numerical checks and failure behaviour

Only the inverse of the fixed Barghini radial law is approximated by a ZPN
polynomial, choosing the first passing odd degree from 3 through 17. Validate
both pixel-to-sky and sky-to-pixel mappings, round trips, and the radial inverse
against the original camera. Tests cover a 137×131 independent grid, 1,027
samples on each detector edge, O/Z, and 100,003 radial samples. Require a
monotonic mapping across the full detector rectangle and maximum additional
error below **0.05 native detector pixel**. This is finite numerical validation,
not a continuum proof or an estimate of the original astrometric uncertainty.

`fits_export.json` records both filenames, success or why export was unavailable. A missing
original, a checksum mismatch against the saved input, incompatible dimensions, unsupported palette/alpha mode or unsuitable
radial model does not produce a substitute image or an inaccurate WCS. An earlier `solution.fits` is preserved as `solution.previous-N.fits` when
replaced or when re-export is refused; the annotated file is likewise preserved
as `solution_annotated.previous-N.fits`. `fits_export.json` records those filenames.
Existing scientific analysis products remain available. Export does not use timestamp,
site, filename-derived epoch or other validation metadata to change the fit.

To export an existing result without running the solver again:

```sh
uv run --project v5 --frozen python v5/point_star_fits.py export /path/to/analysis
```

Use `--image /new/path/to/original.jpg` if the original has moved, and `--output
/new/export/folder` to preserve the existing analysis folder.

## Validation

`test_point_star_fits.py` checks pixels, WCS, metadata independence, source
positions, marker distinctions, crowded label layout, refused exports, and—when
Astrometry.net is installed—loads the plain RGB export with `solve-field` without
an extension override.
`test_point_star_fits_ds9.py` exercises the real DS9 viewer on a private virtual
display, including RGB, Unicode labels, hollow markers, differing line widths,
visibility toggles and the cursor's sky coordinates:

```sh
WFS_TEST_XVFB=/path/to/Xvfb uv run --project v5 --frozen python -m unittest discover -s v5 -p 'test_point_star_fits*.py' -v
```

Without `WFS_TEST_XVFB`, the GUI consumer test is skipped; no desktop windows open.
