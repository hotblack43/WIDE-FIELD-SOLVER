#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
DATABASE="$ROOT_DIR/results/stars.sqlite"
OUTPUT="$ROOT_DIR/results/planet-plots-all-$(date -u +%Y%m%dT%H%M%SZ)"
NIGHTLY_CALIBRATION=""
SKIP_EARLIEST=0

usage() {
    printf '%s\n' \
        "Usage: $0 --nightly-calibration DIR [--database PATH] [--output DIR] [--skip-earliest-observations N]" \
        "" \
        "Plot extinction- and distance-corrected planet photometry for R, G, and B." \
        "By default, read results/stars.sqlite and create a new timestamped" \
        "directory below results/. Existing non-empty output directories are" \
        "never overwritten."
}

while (($#)); do
    case "$1" in
        --database)
            (($# >= 2)) || { printf '%s\n' "ERROR: --database needs a path" >&2; exit 2; }
            DATABASE=$2
            shift 2
            ;;
        --output)
            (($# >= 2)) || { printf '%s\n' "ERROR: --output needs a directory" >&2; exit 2; }
            OUTPUT=$2
            shift 2
            ;;
        --nightly-calibration)
            (($# >= 2)) || { printf '%s\n' "ERROR: --nightly-calibration needs a directory" >&2; exit 2; }
            NIGHTLY_CALIBRATION=$2
            shift 2
            ;;
        --skip-earliest-observations)
            (($# >= 2)) || { printf '%s\n' "ERROR: --skip-earliest-observations needs a number" >&2; exit 2; }
            SKIP_EARLIEST=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf '%s\n' "ERROR: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! $SKIP_EARLIEST =~ ^[0-9]+$ ]]; then
    printf '%s\n' "ERROR: --skip-earliest-observations must be a nonnegative integer" >&2
    exit 2
fi
if [[ -z $NIGHTLY_CALIBRATION ]]; then
    printf '%s\n' "ERROR: --nightly-calibration DIR is required" >&2
    exit 2
fi
if [[ ! -d $NIGHTLY_CALIBRATION ]]; then
    printf '%s\n' "ERROR: nightly calibration directory does not exist: $NIGHTLY_CALIBRATION" >&2
    exit 1
fi
if [[ ! -f $DATABASE ]]; then
    printf '%s\n' "ERROR: planet database does not exist: $DATABASE" >&2
    exit 1
fi
if [[ -d $OUTPUT ]] && [[ -n $(find "$OUTPUT" -mindepth 1 -maxdepth 1 -print -quit) ]]; then
    printf '%s\n' "ERROR: output directory is not empty: $OUTPUT" >&2
    exit 1
fi
if [[ -e $OUTPUT ]] && [[ ! -d $OUTPUT ]]; then
    printf '%s\n' "ERROR: output path exists and is not a directory: $OUTPUT" >&2
    exit 1
fi

mkdir -p "$OUTPUT"
LOG="$OUTPUT/plot_ALL_planets.log"
exec > >(tee -a "$LOG") 2>&1

failed() {
    local status=$?
    printf '\nERROR: planet plotting stopped with status %d.\n' "$status"
    printf 'See log: %s\n' "$LOG"
    exit "$status"
}
trap failed ERR

printf 'Planet database: %s\n' "$DATABASE"
printf 'Extinction-correction sidecar: %s\n' "$NIGHTLY_CALIBRATION"
printf 'Output directory: %s\n' "$OUTPUT"
printf 'Product: extinction- and distance-corrected photometry\n'
printf 'Channels: R, G, B\n'

run_number=0
for channel in R G B; do
    channel_output="$OUTPUT/$channel"
    common=(
        uv run --project "$ROOT_DIR" --frozen python
        "$ROOT_DIR/scripts/plot_planet_photometry.py"
        --database "$DATABASE"
        --output "$channel_output"
        --channel "$channel"
        --skip-earliest-observations "$SKIP_EARLIEST"
    )

    ((++run_number))
    printf '\n[%d/5] %s channel: extinction- and distance-corrected photometry\n' \
        "$run_number" "$channel"
    "${common[@]}" \
        --extinction-corrected-distance-corrected \
        --nightly-calibration "$NIGHTLY_CALIBRATION"
done

printf '\n[4/5] Combined planetary colour-colour diagram\n'
uv run --project "$ROOT_DIR" --frozen python \
    "$ROOT_DIR/scripts/plot_planet_colours.py" \
    --input-root "$OUTPUT" \
    --output "$OUTPUT"

printf '\n[5/5] Brightness-matched stellar extinction diagnostic\n'
uv run --project "$ROOT_DIR" --frozen python \
    "$ROOT_DIR/scripts/plot_brightness_matched_planet_extinction.py" \
    --stellar-measurements \
    "$NIGHTLY_CALIBRATION/calibration_star_measurements.csv" \
    --planet-root "$OUTPUT" \
    --output "$OUTPUT"

printf '\nAll planet plots completed.\n'
printf 'Outputs: %s\n' "$OUTPUT"
printf 'Log: %s\n' "$LOG"
