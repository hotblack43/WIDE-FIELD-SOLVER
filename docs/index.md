# Blind astrometry across the whole fisheye image

WIDE-FIELD SOLVER detects point sources, identifies stars and fits the Barghini
O/Z fisheye model across an extreme wide-angle detector. The stellar solution
does not need an observing site, camera orientation or image timestamp as a
starting condition.

<figure markdown="span">
  ![Solved colour MMT Observatory all-sky image with catalogue-star labels, Jupiter, a provisional zenith and the predicted position of Uranus](https://raw.githubusercontent.com/hotblack43/WIDE-FIELD-SOLVER/main/reports/wide-field-diagnostics/figures/mmto_sky_overlay.png){ .wfs-hero }
  <figcaption>MMTO colour FITS image after the v0.9.0 astrometric fit.</figcaption>
</figure>

<div class="wfs-result" markdown>

## A representative MMTO result

One colour FITS image produced **1,380 stellar matches** with
**0.3267-pixel RMS**, a **0.2350-pixel median** residual and a
**0.4964-pixel 90th percentile**. These are fitted residuals, not an
independent withheld-star validation.

</div>

## The analysis path

1. Detect point sources while retaining broad and saturated objects.
2. Obtain a blind catalogue bootstrap from measured image positions.
3. Fit the camera and Barghini lens model in angular sky coordinates.
4. Measure instrumental photometry and test separate zenith, extinction and
   epoch constraints.
5. Write a report, tables, provenance and an append-only database record.

The planetary stage is separate. When image-time metadata is available, the
normal v0.9.0 run uses it only after stellar astrometry is fixed and labels the
result as metadata-conditioned. A full blind planet search remains available.

[Solve a first image](QUICKSTART.md){ .md-button .md-button--primary }
[Understand the scientific status](SCIENTIFIC_STATUS.md){ .md-button }
