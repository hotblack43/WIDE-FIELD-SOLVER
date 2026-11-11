# Corrected complete historical radial-model result

This tracked directory is review-sized evidence from the corrected complete
24 September 2026 run. The row-level 2.4 GB product is
`results/radial-model-study-v12-corrected`; the CSV files here retain every
image/model row, robust operational metrics, and compact per-image/radial-bin
association and planet summaries.

The earlier `radial-model-study-v12` run is superseded. Review found that it
used an obsolete gate location, substituted gate defaults, interleaved nearby
points between train and test folds, omitted the fitted Gaussian variance from
the information-criterion parameter count, and did not retain the robust fit
records. None of its numerical conclusions are used below.

## Statistical answer

The corrected inventory contained 683 saved result files and 432 unique
successful image checksums in 19 source groups. All 432 were analyzed. A radial
extension passed the predeclared AICc, BIC, contiguous-block validation, and
bootstrap rules for 51 images (11.8%); 381 retained `M0`. Selected orders were
`M1=10`, `M2=6`, `M3=0`, `M4=25`, and `M5=10`.

Among those 51 selected extensions, the ordinary Gaussian fit's median pixel
RMS change was -0.02497 pixel (-7.49%). Median RMS on held-out annular wedges
changed by -0.2136 arcmin. A source-group cluster bootstrap gives a 95% interval
of -0.7365 to -0.2027 arcmin for the median held-out change. The separate robust
operational comparison has a median change of -0.02331 pixel and -0.2080
arcmin among the 50 extensions whose robust selected fit succeeded.

The benefit is strongly camera-specific. The main 1411x1422 MMTO group selected
an extension in 44/221 images. APICAM selected one in only 1/111, all 35 Subaru
images retained `M0`, and all 50 Zenodo R/G images retained `M0`. The ordinary
blind solver therefore remains on the inherited model; the evidence supports a
per-image or carefully camera-family-specific decision, not a universal added
polynomial.

## Already-detected stellar sources

Source detection was never rerun or changed. Exact saved association gates and
catalogue/detection inputs were available for 427 images. Three images lacked a
saved stellar gate and two selected robust fits failed; those cases are
explicitly unavailable rather than evaluated with a substitute gate.

Among the 49 extension-selected images with an operational comparison, the same
detection lists produced 681 gained, 84 lost, 917 identity-changed, 52,463
common, and 7,491 still-unmatched detections. Forty-two images had a positive
net gain, two a negative net, and five no net change. The median image gained
nine associations net.

The practical effect is concentrated at the field rim. In the populated outer
annulus `0.50 <= r/R < 0.75`, where `R` is half the detector diagonal, there
were 648 gains and 54 losses: net +594. Common/changed outer matches had a
median residual change of -0.1850 arcmin. Thus the extra terms can make
additional *already detected* edge sources acceptable catalogue fits. They do
not find new image objects; changing detection completeness would require a
separate detection experiment.

## Fixed planet-candidate sensitivity

The planet table contains 105,582 historical candidate rows on 396 images. Each
row keeps its measured detection, body identity, and epoch fixed. These are
conditional candidate residuals, not confirmed bodies and not a rerun of blind
planet identification.

For the 45 extension-selected images with usable candidate comparisons, 8,709
candidate residuals improved and 10,002 worsened; the median selected-minus-
baseline separation was +0.0732 arcmin. In the outer field (`r/R >= 0.5`) the
median change was worse by +0.2356 arcmin. Of rows with recorded gates, only 44
crossed from outside to inside while 341 crossed from inside to outside. The
minor-planet subset contributed 8 entries and 67 exits. A further 347 extension
rows have `gate_unavailable`, because their historical sidecars did not record
a gate; no 30-arcmin default was invented.

Consequently these stellar plate terms do **not** show that edge planets or
minor planets generally become good fits. On this fixed-candidate test they
more often move a proposed body out of its historical acceptance gate. A true
planet-recovery claim would require rerunning the blind search with the selected
extended camera, not merely reprojecting retained candidates.

## Failure and sensitivity evidence

Full-data optimizer failures by order were `M0=3`, `M1=13`, `M2=88`,
`M3=366`, `M4=49`, and `M5=144`. Across extended orders there were also many
valid but rejected results: `M1` alone had 133 in-sample-only and 147
worse-prediction cases. Two selected robust fits failed. The extremely high
`M3` failure rate and the non-universal predictive result are important failure
modes, not reasons to relax the selection thresholds.

One retained metadata limitation does not affect fitting or selection:
serialized extended cameras currently set `monotonic_on_detector` from the
combined full-corner validity result. An unused corner beyond the antipode can
therefore make that convenience boolean false even when the separately tested
detector-wide radial derivative is positive. The detailed validation reason and
the fit status remain authoritative.

## Audit

The independent audit recomputed AIC, AICc, and BIC with zero discrepancy and
verified that every criterion counted the camera parameters plus one fitted
Gaussian variance. Akaike weights agree to `2.22e-16`. Every source has six
model rows and eight fold rows per order; holdout totals reproduce every fitted
membership and all membership hashes are well-formed. Fold construction and
train/holdout exclusion are independently covered by regression tests; the
streaming audit does not reconstruct hashes from the original coordinate rows.
All 432 operational records
decode, selected coefficient counts match their orders, and all 1,791,314
stellar association rows use the exact recorded per-image gate. See
`summary.json` for the complete audit and `MANIFEST.json` for compact-file row
counts.
