#!/usr/bin/env bash
# Process verified MMTO images with v19 and add variable-star time series.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unset VIRTUAL_ENV
exec uv run --project "$repo" --frozen python \
    "$repo/scripts/run_mmto_photometry_pipeline_v19.py" "$@"
