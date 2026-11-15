# Visible-sky mask calibrations

This directory holds approved, immutable camera-installation masks and their
JSON manifests. Pixel value 255 means usable visible sky; pixel value 0 means
excluded foreground. Arrays use `mask[y, x]` with the origin at the detector's
top-left pixel.

Drafts are never stored here. Review-only proposals live under
`examples/mmto/visible_sky_mask_review/` and cannot be selected by a production
launcher. Moving, rotating, or replacing a camera requires a new installation
identifier and a new approved artifact; existing masks are never overwritten.

The registry.jsonl file is the bundled read-only calibration layer. Each
calibration record verifies its adjacent manifest and mask by SHA-256. User
calibration roots use the same append-only schema in a separate writable
registry. Registration does not activate an installation; activation is a
distinct append-only record used only for future source assignments.

Source assignments live outside this bundled read-only directory. They bind an
exact raw-file SHA-256 to the selected installation, manifest, and mask hashes;
observation time never infers an installation. A future activation cannot
repoint an earlier assignment. The downloader writes assignments only when all
three opt-in calibration options are supplied, and preserves a verified raw
file as explicitly unassigned if validation fails.

The bundled MMTO calibration is production-approved evidence for one physical
installation. The generic registry and calibration tools are camera-neutral,
but no real non-MMTO installation has yet completed the full cold-start review.
