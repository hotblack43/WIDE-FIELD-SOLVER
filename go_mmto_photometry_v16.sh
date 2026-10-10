#!/usr/bin/env bash
# Process verified MMTO images with the independent v16 celestial-gate solver.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$repo" --frozen python \
    "$repo/scripts/run_mmto_photometry_pipeline_v16.py" "$@"
