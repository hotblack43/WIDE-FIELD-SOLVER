# Zenodo 3736793 go6 trial

Source: Peter Thejll, *All-sky camera images from the Subaru telescope on
Mauna Kea*, Zenodo record 3736793, DOI
<https://doi.org/10.5281/zenodo.3736793>.

Downloaded through the Zenodo record API on 2026-09-17. The public file list
contained 51 R frames and 8 G frames, but no B frame, despite the record
description mentioning R, G and B. These three native FITS files were selected
as a small trial; the matched R/G pair has the same JD and 16 s exposure.

| File | Zenodo MD5 | go6 trial |
|---|---|---|
| `R_darksubtracted_JD2458939.6201835_16000000.fits` | `785954b71c8a8c0a836ebad4f2dc9036` | 159 candidates; 40 Gaia fits; 1.6800 px RMS |
| `G_darksubtracted_JD2458939.6201835_16000000.fits` | `8d12fb3f1211a613e6d445767d7d12e8` | 138 candidates; 46 Gaia fits; 1.7989 px RMS |
| `R_darksubtracted_JD2458939.5628889_16000000.fits` | `73cafa27ce24c1f19a2a4f2879084897` | downloaded, not yet run |

The camera acquisition can provide 14-bit samples. The downloaded dark-subtracted
products are 488 x 652 floating-point physical samples (`BITPIX=-64`), so their
storage type must not be mistaken for the acquisition depth. No authoritative
saturation keyword is present, so go6 records saturation as unknown rather than
inventing a threshold.

The successful matched-frame runs used only image pixels for the blind solve:

```sh
./go6.sh data/zenodo-3736793/trial/R_darksubtracted_JD2458939.6201835_16000000.fits
./go6.sh data/zenodo-3736793/trial/G_darksubtracted_JD2458939.6201835_16000000.fits
```

Both results were appended to the normal go6 SQLite run database. Their stellar
epochs remain explicitly not identifiable; the astrometric fits do not use the
JD embedded in the filename or header.
