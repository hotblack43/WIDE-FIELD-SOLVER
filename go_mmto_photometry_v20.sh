#!/usr/bin/env bash
# Download and process a bounded backward MMTO batch with v20.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unset VIRTUAL_ENV
exec uv run --project "$repo" --frozen python \
    "$repo/scripts/run_mmto_photometry_pipeline_v20.py" "$@" \
    --results-dir "$repo/results"
