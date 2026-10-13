#!/usr/bin/env bash
# Convenience launcher pinned to the early celestial-gate solver 0.17.0.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
expected_version='0.17.0'

usage() {
    echo "Usage: $0 IMAGE [IMAGE ...] [native-input options]"
    echo "  IMAGE may be a shell-expanded wildcard, for example: images/*.fits.bz2"
    echo "  --results-dir PATH  store runs and stars.sqlite here"
    echo "  Default: WFS_RESULTS_DIR, host-specific user config, then $repo/results"
    echo "  --fits-hdu NAME_OR_INDEX"
    echo "  --channel-order RGB|RGGB|RG1G2B"
    echo "  --saturation-level VALUE_OR_CHANNEL_MAP"
    echo "  --blind-planets  ignore EXIF/FITS/filename time and run the full blind planet search"
    echo "  --flat-only  publish stable input-based filenames directly in results-dir"
    echo "Runs solver $expected_version with Gaia; ordinary runs append to stars.sqlite."
}

if [[ $# -lt 1 ]]; then
    usage >&2
    exit 2
fi
inputs=()
solver_args=()
results_override="${WFS_RESULTS_DIR:-}"
flat_only=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --version)
            echo "Wide-field go17 $expected_version (requires solver $expected_version)"
            exit 0
            ;;
        --results-dir)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "Missing value for $1" >&2
                exit 2
            fi
            results_override="$2"
            shift 2
            ;;
        --blind-planets)
            solver_args+=("$1")
            shift
            ;;
        --flat-only)
            flat_only=1
            shift
            ;;
        --fits-hdu|--channel-order|--saturation-level)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "Missing value for $1" >&2
                exit 2
            fi
            solver_args+=("$1" "$2")
            shift 2
            ;;
        --)
            shift
            inputs+=("$@")
            break
            ;;
        -*)
            echo "Unsupported go17 option: $1" >&2
            usage >&2
            exit 2
            ;;
        *)
            inputs+=("$1")
            shift
            ;;
    esac
done

if [[ ${#inputs[@]} -eq 0 ]]; then
    echo "No image files were supplied." >&2
    usage >&2
    exit 2
fi
images=()
for input in "${inputs[@]}"; do
    if [[ ! -f "$input" ]]; then
        echo "Image file does not exist: $input" >&2
        exit 2
    fi
    images+=("$(realpath -- "$input")")
done

# Resolve every runtime dependency inside the independent v17 directory.
solver="$repo/v17"
catalogue="$solver/data/stars_gaia_dr3_g75.csv"
if [[ ! -x "$solver/analyse.sh" || ! -f "$catalogue" ]]; then
    echo "Packaged Gaia solver $expected_version is incomplete at $solver." >&2
    exit 2
fi
actual_version="$("$solver/analyse.sh" --version)"
if [[ "$actual_version" != *" $expected_version" ]]; then
    echo "Version mismatch: this launcher requires $expected_version; solver reports $actual_version" >&2
    exit 2
fi

# The per-host preference is outside the repository, so a checkout at home
# remains portable even when the home directory/config is shared between hosts.
results_config="${XDG_CONFIG_HOME:-$HOME/.config}/wide-field-solver/results-dir.$(hostname)"
results_root="$repo/results"
if [[ -n "$results_override" ]]; then
    results_root="$results_override"
elif [[ -f "$results_config" ]]; then
    results_root="$(head -n 1 -- "$results_config")"
    if [[ "$results_root" != /* || ! -d "$results_root" || ! -w "$results_root" ]]; then
        echo "Configured results directory is unavailable: $results_root" >&2
        echo "Check its mount or use --results-dir PATH. Setting: $results_config" >&2
        exit 2
    fi
fi
if [[ $flat_only -eq 1 ]]; then
    mkdir -p -- "$results_root"
else
    mkdir -p -- "$results_root/runs"
fi
results_root="$(realpath -- "$results_root")"

declare -A flat_names=()
if [[ $flat_only -eq 1 ]]; then
    for image in "${images[@]}"; do
        flat_filename="${image##*/}"
        flat_filename="${flat_filename%.bz2}"
        flat_stem="${flat_filename%.*}"
        flat_stem="${flat_stem//[^a-zA-Z0-9._-]/_}"
        flat_stem="${flat_stem:0:160}"
        if [[ -n "${flat_names[$flat_stem]:-}" ]]; then
            echo "Flat output name collision for $image and ${flat_names[$flat_stem]}" >&2
            exit 2
        fi
        flat_names[$flat_stem]="$image"
    done
fi

succeeded=0
failed=0
for image in "${images[@]}"; do
    filename="${image##*/}"
    stem="${filename%.*}"
    stem="${stem//[^a-zA-Z0-9._-]/_}"
    stem="${stem:0:80}"
    if [[ $flat_only -eq 1 ]]; then
        filename="${filename%.bz2}"
        stem="${filename%.*}"
        stem="${stem//[^a-zA-Z0-9._-]/_}"
        stem="${stem:0:160}"
        run_dir="$(mktemp -d "${TMPDIR:-/tmp}/wfs-v17-${stem:-image}-XXXXXX")"
    elif ! run_dir="$(mktemp -d "$results_root/runs/${stem:-image}-v${expected_version}-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"; then
        echo "Cannot create a run in $results_root; use --results-dir on a filesystem with free space." >&2
        failed=$((failed + 1))
        continue
    fi
    output="$run_dir/analysis"

    echo "Solver: $actual_version, Gaia DR3"
    echo "Image: $image"
    if [[ $flat_only -eq 1 ]]; then
        echo "Temporary work folder: $run_dir"
    else
        echo "Run folder: $run_dir"
    fi
    echo "Images and reports: $output"
    echo "Log: $run_dir/run.log"
    if [[ $flat_only -eq 0 ]]; then
        echo "Database: $results_root/stars.sqlite"
    fi

    analyse_args=("$image" --catalog "$catalogue" --epoch-mode fit --output "$output")
    if [[ $flat_only -eq 0 ]]; then
        analyse_args+=(--database "$results_root/stars.sqlite")
    fi
    analyse_args+=("${solver_args[@]}")
    if ! OPENBLAS_NUM_THREADS=1 "$solver/analyse.sh" "${analyse_args[@]}" \
            2>&1 | tee "$run_dir/run.log"; then
        if [[ $flat_only -eq 1 ]]; then
            echo "Analysis failed; temporary work files will be removed: $run_dir" >&2
        else
            echo "Analysis failed. Its output and log are preserved at $run_dir" >&2
        fi
        failed=$((failed + 1))
        if [[ $flat_only -eq 1 ]]; then rm -rf -- "$run_dir"; fi
        continue
    fi

    report="$output/report.pdf"
    if [[ ! -f "$report" ]]; then
        echo "Analysis finished without a report PDF. See $run_dir/run.log" >&2
        failed=$((failed + 1))
        if [[ $flat_only -eq 1 ]]; then rm -rf -- "$run_dir"; fi
        continue
    fi

    flat_prefix="${stem}"
    if [[ $flat_only -eq 0 ]]; then flat_prefix="${run_dir##*/}"; fi
    flat_failed=0
    for product in report.pdf solution.fits solution_annotated.fits; do
        source_product="$output/$product"
        flat_product="$results_root/${flat_prefix}__${product}"
        if [[ ! -f "$source_product" ]]; then
            echo "Analysis finished without $product. See $run_dir/run.log" >&2
            flat_failed=1
            continue
        fi
        partial_product="$flat_product.partial.$$"
        if ! cp --reflink=auto -- "$source_product" "$partial_product" || \
                ! mv -f -- "$partial_product" "$flat_product"; then
            rm -f -- "$partial_product"
            echo "Cannot publish flat product: $flat_product" >&2
            flat_failed=1
            continue
        fi
        printf 'Flat product: %s\n' "$flat_product"
    done
    if [[ $flat_failed -ne 0 ]]; then
        failed=$((failed + 1))
        if [[ $flat_only -eq 1 ]]; then rm -rf -- "$run_dir"; fi
        continue
    fi
    succeeded=$((succeeded + 1))
    if [[ $flat_only -eq 1 ]]; then
        printf '\nImages and reports: %s\n' "$results_root"
        printf 'Report: %s\n' "$results_root/${flat_prefix}__report.pdf"
        rm -rf -- "$run_dir"
    else
        printf '\nImages and reports: %s\n' "$output"
        printf 'Report: %s\n' "$report"
    fi
done

if [[ ${#images[@]} -gt 1 ]]; then
    printf '\nBatch summary: %d succeeded, %d failed.\n' "$succeeded" "$failed"
fi
if [[ $failed -gt 0 ]]; then
    exit 1
fi
