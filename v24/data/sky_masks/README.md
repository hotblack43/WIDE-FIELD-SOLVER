# Visible-sky mask calibrations

This directory holds approved, immutable camera-installation masks and their
JSON manifests. Pixel value 255 means usable visible sky; pixel value 0 means
excluded foreground. Arrays use `mask[y, x]` with the origin at the detector's
top-left pixel.

Drafts are never stored here. Review-only proposals live under
`examples/mmto/visible_sky_mask_review/` and cannot be selected by a production
launcher. Moving, rotating, or replacing a camera requires a new installation
identifier and a new approved artifact; existing masks are never overwritten.
