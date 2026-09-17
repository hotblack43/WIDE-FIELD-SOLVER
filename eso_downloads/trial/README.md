# ESO APICAM trial and archive scope

APICAM is ApiCam-3 at Paranal, not the La Silla LASC camera. ESO's
combined La Silla Paranal Observatory archive can make this distinction easy
to miss.

Trial dataset: `APICAM.2018-03-01T00:13:02.000`

- Source query: APICAM raw data, 2018-03-01 through 2018-03-02, one row.
- File: `APICAM.2018-03-01T00:13:02.000.fits`
- SHA-256: `9d65d31113e85b8aa691d503800fbc33b45f025746d7e8012c9b93aad8a63de8`
- FITS: one 4096 x 4096 unsigned 16-bit image (`BITPIX=16`, `BZERO=32768`).
- Exposure: 120 s; filter: Luminance; date: 2018-03-01T00:13:02.
- Size: 33,557,760 bytes.
- Exactly 58,621 pixels (0.3494%) are at 65535; no `SATURATE` keyword.
- Percentiles 1/50/99: 620 / 3868 / 34193.85 ADU.

Archive counts queried from ESO on 2026-09-17:

| Period | APICAM records |
|---|---:|
| 2018 | 50,817 |
| 2019 | 52,643 |
| 2020 | 15,257 |
| Total | 118,717 |

The records span 2018-03-01 through 2020-06-25. At the trial file size, a
complete uncompressed download would be about 3.98 TB (3.62 TiB). The first
ten March 2018 records have a median interval of 147 seconds, so sparse
time-based selection is preferable to downloading every exposure.

`eso-download raw --instrument LASC --count-only` returned zero records. The
La Silla live LASC system is separate from this APICAM collection.
