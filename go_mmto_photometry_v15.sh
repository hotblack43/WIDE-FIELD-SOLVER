#!/usr/bin/env bash
# Process verified MMTO images with the independent v15 celestial-gate solver.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$repo" --frozen python \
    "$repo/scripts/run_mmto_photometry_pipeline_v15.py" "$@"
