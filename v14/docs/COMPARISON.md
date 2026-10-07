# Barghini versus solve-field: this fisheye image

The direct full-image solve-field runs did not produce a solution. On a 260 × 260-pixel crop, using our measured dots and third-order SIP distortion, solve-field reached 0.390-pixel RMS on the same 195 stars for which Barghini gives 0.406 pixel. The demonstrated advantage is full-field coverage, not uniquely achievable local precision.

| Input to solve-field | Distortion | Outcome | Elapsed | RMS on all 195 common crop stars |
|---|---|---|---:|---:|
| Whole original JPEG | SIP 2 | Unsolved | 125.1 s | — |
| Whole image, our 3,688 dots | SIP 2 | Unsolved | 129.4 s | — |
| Whole image, our dots; smaller patterns, 3-pixel tolerance, deeper search | SIP 5 | Stopped, unsolved | 333.1 s | — |
| Crop PNG; built-in source extraction | SIP 2 | Solved | 2.3 s | 8.192 px |
| Crop PNG; built-in source extraction | SIP 3 | Solved | 2.3 s | 8.941 px |
| Crop PNG; built-in source extraction | SIP 5 | Solved | 3.3 s | Inverse failed for 12 stars |
| Crop; our measured dots | SIP 3 | Solved | 1.0 s | 0.390 px |
| Crop; our measured dots | SIP 5 | Solved | 2.1 s | 0.444 px |

Barghini: **3,653 associated stars across the full image, 0.398-pixel RMS**. The successful crop covers approximately 28° × 29°, only 3% of the rectangular image area.

## Conditions and limits

- Local astrometry.net / solve-field version 0.93. No online submission.
- Tycho-2 indices 4107–4119 cover pattern scales of about 0.37°–32°. Missing indices 4114–4119 were downloaded from the [official index archive](https://data.astrometry.net/4100/), into this experiment only.
- Full-image inputs carried no RA, Dec, date, location, orientation, scale or lens hints. The dot-list runs received only measured x/y and intensity.
- The control crop location was chosen from the previously successful tetra3 patch; solve-field was not given its celestial solution.
- The two standard full-image runs reached their requested 120-second CPU limits. The relaxed run was stopped after 333 seconds elapsed because its requested 180-second limit did not stop the engine. This is a bounded experiment, not proof that every possible solve-field configuration must fail.
- Common-star residuals use the existing Barghini association table for evaluation only. No stars were deliberately withheld. These are comparative residuals, not independent accuracy certification.
- All 195 common crop stars are scored, without residual clipping. The fifth-order PNG solution failed to invert for 12 stars; these failures are not counted as good residuals.
- Cropping, tiling, reprojection and a separate global lens fit could extend an astrometry.net-based workflow. They were not substituted for a direct full-image solve here.

The preserved [comparison.json](comparison.json) contains commands, outcomes and numeric scores; [provenance.json](provenance.json) records the image and index checksums. Personal paths have been replaced by `COMPARISON_WORKDIR`, `INDEX_DIRECTORY`, and the included image's relative path. These command arrays document the historical experiment; its temporary dot lists, crop images, logs, WCS products and large index files are not bundled. The normal Barghini demo needs none of the astrometry.net installation or indices.
