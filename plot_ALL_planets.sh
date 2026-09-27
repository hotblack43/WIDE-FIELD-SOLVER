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
        "Plot all planet products for the R, G, and B channels." \
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
printf 'Nightly stellar calibration: %s\n' "$NIGHTLY_CALIBRATION"
printf 'Output directory: %s\n' "$OUTPUT"
printf 'Products: raw, distance-corrected, nightly stellar-calibrated distance-corrected\n'
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
    printf '\n[%d/9] %s channel: raw instrumental photometry\n' "$run_number" "$channel"
    "${common[@]}"

    ((++run_number))
    printf '\n[%d/9] %s channel: distance-corrected photometry\n' "$run_number" "$channel"
    "${common[@]}" --distance-corrected

    ((++run_number))
    printf '\n[%d/9] %s channel: nightly stellar-calibrated distance-corrected photometry\n' \
        "$run_number" "$channel"
    "${common[@]}" \
        --nightly-stellar-calibrated-distance-corrected \
        --nightly-calibration "$NIGHTLY_CALIBRATION"
done

printf '\nAll planet plots completed.\n'
printf 'Outputs: %s\n' "$OUTPUT"
printf 'Log: %s\n' "$LOG"
