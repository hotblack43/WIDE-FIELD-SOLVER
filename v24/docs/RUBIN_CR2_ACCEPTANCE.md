# Rubin CR2 direct-ingestion acceptance

The v0.10.0 acceptance run used the unchanged public Rubin all-sky exposure
`asc2506240487.cr2`, SHA-256
`ab36ba13f71f19d10ca6c0b4597abd6efbfc46f8dd77802be9bb17711eceed2d`.
It was invoked once with:

```sh
./go10.sh /path/to/asc2506240487.cr2 --results-dir /path/to/rubin-v10-acceptance
```

The retained run decoded `raw_image_visible` with rawpy/LibRaw as RGGB and
stored four 2251×3372 `uint16` planes. Effective depth is 14 bits; black levels
are R=2049, G1=2050, G2=2049 and B=2050 ADU. EXIF gives 30 s, ISO 400,
Canon EOS 5D Mark IV and EF8-15mm f/4L FISHEYE USM. Capture time
2025-06-25 04:06:01 UTC was read only after the blind stellar fit was fixed.

The direct run detected 1,575 candidates and fitted 1,507 stars at 0.695829372
pixel RMS (2.867788 arcmin). The earlier conversion-assisted run fitted the
same 1,507 stars at 0.695829381 pixel RMS; the difference is below 1e-8 pixel.

The saved image-only mask accepts 4,865,456 pixels and excludes 2,724,916
non-sky pixels. Its maximum fitted angle is 92.496941 degrees. Mask-restricted
ZPN validation passed at 0.014029631 pixel maximum added error, below the
unchanged 0.05-pixel limit. Inspection confirmed that:

- every non-sky pixel in `solution.fits` is NaN and every accepted pixel retains
  the derived luminance;
- annotated `RED/GREEN1/GREEN2/BLUE` arrays exactly equal the native decoded
  planes;
- annotated `SKYMASK` exactly equals `dots/sky_footprint.npz`.

This acceptance demonstrates direct scientific CR2 ingestion. It does not
claim calibrated photometry or independent validation of the fitted catalogue.
