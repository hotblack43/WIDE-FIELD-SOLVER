# V25 Visible-Sky Operator Workflow Design

## Intent

Turn the accepted generic v24 visible-sky calibration machinery into an
independent v25 runtime with one public operator entry point. V24 becomes a
frozen scientific checkpoint. V25 retains its numerical behaviour and adds a
configuration-driven command that makes proposal, revision, approval, and
activation discoverable without requiring operators to assemble internal
Python commands.

## Version boundary

- The final v24 checkpoint includes the accepted MMTO cold-start candidate,
  receipt, fixed thresholds, executable acceptance check, and current v24
  runtime files.
- Record that checkpoint in `docs/v24-runtime.json` and protect it with a
  boundary test before v25 development changes runtime behaviour.
- Copy the complete v24 package into `v25/`; v25 must not import v24.
- Add independent `go25.sh`, `go_v0.25.0.sh`, and
  `go_mmto_photometry_v25.sh` launchers and the v25 MMTO pipeline support they
  invoke. Existing v24 launchers remain byte-for-byte unchanged after the
  boundary is recorded.
- V25 reports version `0.25.0`, owns its catalogue, lockfile, ephemeris data,
  mask data, example, and source manifest, and works without `.worktrees`.

## Public calibration command

The public entry point is `go_visible_sky_v25.sh`. It executes the v25 locked
environment and exposes four explicit stages:

```sh
./go_visible_sky_v25.sh propose --config cameras/my-camera.toml
./go_visible_sky_v25.sh revise --config cameras/my-camera.toml \
  --parent-selection PATH --edited-mask PATH --output PATH
./go_visible_sky_v25.sh approve --config cameras/my-camera.toml \
  --proposal PATH --reviewed-draft-sha256 SHA256 \
  --mask-id MASK_ID --approved-by NAME
./go_visible_sky_v25.sh activate --config cameras/my-camera.toml
```

The stages remain separate. In particular, `propose` never approves and
`approve` never activates. Existing immutable proposal, revision, approval,
registry, detector-signature, and checksum rules remain unchanged.

## Configuration

Configuration uses Python 3.12's standard `tomllib` and schema
`wide-field-solver-visible-sky-operator-v1`. Required keys are:

```toml
schema = "wide-field-solver-visible-sky-operator-v1"
source_id = "example"
camera_id = "camera-a"
installation_id = "example-camera-2026a"
orientation = "detector_native_top_left_xy_right_y_down"
download_manifest = "../raw_allsky_samples/manifest.sqlite"
archive_root = "../raw_allsky_samples"
review_root = "../calibration-review"
calibration_root = "../camera-calibrations"
```

Relative paths resolve relative to the configuration file, not the current
working directory. Unknown keys, missing keys, empty identifiers, unsafe
installation identifiers, missing managed inputs, and non-file configuration
paths fail before any output is written. `propose` defaults to
`review_root/installation_id`; an explicit `--output` may override that path.
Approval writes to `calibration_root`, whose registry is
`calibration_root/registry.jsonl`. Activation uses that registry and the
source, camera, and installation identifiers from the configuration.

The repository includes a complete commented example configuration that uses
placeholders rather than claiming another camera has been validated.

## Solving and routine processing

`go25.sh` preserves the v24 image-solving interface. Assigned managed images
continue to resolve through the calibration registry and assignment records;
arbitrary local images continue to accept the explicit mask-manifest and
installation pair. The routine MMTO command becomes:

```sh
./go_mmto_photometry_v25.sh
```

The MMTO scientific path and accepted mask remain numerically unchanged at the
v25 boundary. Only v25 receipts count as completed v25 masked solver work;
predecessor receipt handling must be stated and tested rather than inferred by
text substitution.

## Packaging and documentation

The v25 README leads with the real commands above, not the demo. The demo
remains a verification tool. Root documentation identifies v24 as frozen and
v25 as active development. The source manifest includes every tracked or
new v25 runtime file and the example configuration.

This work prepares v25 for a curated downloadable release but does not create a
GitHub tag or publish externally without a separate explicit publication step.

## Non-goals

- No automatic visual approval or activation.
- No change to the visible-sky numerical classifier or accepted MMTO mask.
- No claim of real non-MMTO validation.
- No import or runtime fallback from v25 into v24.
- No deletion, hiding, or replacement of historical launchers or evidence.
- No repair of the unrelated host-specific offload-path test as part of v25.
