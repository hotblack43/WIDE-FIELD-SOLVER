#!/usr/bin/env bash
# Convenience launcher pinned to the Gaia-capable wide-field solver 0.4.2.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
expected_version='0.4.2'

usage() {
    echo "Usage: $0 /full/path/to/image.jpg"
    echo "Runs solver $expected_version with Gaia; outputs go under $repo/results/runs/."
}

if [[ $# -ne 1 ]]; then
    usage >&2
    exit 2
fi
case "$1" in
    -h|--help) usage; exit 0 ;;
    --version) echo "Wide-field go $expected_version (requires solver $expected_version)"; exit 0 ;;
esac
if [[ ! -f "$1" ]]; then
    echo "Image file does not exist: $1" >&2
    exit 2
fi
image="$(realpath -- "$1")"

# A checkout of v0.4 uses its own solver. The preserved root checkout delegates
# explicitly to the isolated Gaia worktree; it must never fall back to v0.1.
solver="$repo"
if [[ ! -f "$solver/data/stars_gaia_dr3_g75.csv" ]]; then
    solver="$repo/.worktrees/planets-v0.4.2"
fi
catalogue="$solver/data/stars_gaia_dr3_g75.csv"
if [[ ! -x "$solver/analyse.sh" || ! -f "$catalogue" ]]; then
    echo "Gaia solver $expected_version is unavailable at $solver." >&2
    echo "Use a checkout of feature/planets-v0.4.2, or keep its worktree in .worktrees/planets-v0.4.2." >&2
    exit 2
fi
actual_version="$("$solver/analyse.sh" --version)"
if [[ "$actual_version" != *" $expected_version" ]]; then
    echo "Version mismatch: this launcher requires $expected_version; solver reports $actual_version" >&2
    exit 2
fi

filename="${image##*/}"
stem="${filename%.*}"
stem="${stem//[^a-zA-Z0-9._-]/_}"
stem="${stem:0:80}"
mkdir -p "$repo/results/runs"
run_dir="$(mktemp -d "$repo/results/runs/${stem:-image}-v${expected_version}-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
output="$run_dir/analysis"

echo "Solver: $actual_version, Gaia DR3"
echo "Image: $image"
echo "Run folder: $run_dir"
echo "Images and reports: $output"
echo "Log: $run_dir/run.log"

if ! OPENBLAS_NUM_THREADS=1 "$solver/analyse.sh" "$image" \
        --catalog "$catalogue" --epoch-mode fit --output "$output" \
        2>&1 | tee "$run_dir/run.log"; then
    echo "Analysis failed. Its output and log are preserved at $run_dir" >&2
    exit 1
fi

shopt -s nullglob
reports=("$output"/report_*.pdf)
if [[ ${#reports[@]} -eq 0 ]]; then
    echo "Analysis finished without a report PDF. See $run_dir/run.log" >&2
    exit 1
fi
printf '\nImages and reports: %s\n' "$output"
printf 'Report: %s\n' "${reports[@]}"
