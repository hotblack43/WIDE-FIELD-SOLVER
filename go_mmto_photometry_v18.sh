#!/usr/bin/env bash
# Backfill and process MMTO images with the independent v18 runtime.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$repo" --frozen python \
    "$repo/scripts/run_mmto_photometry_pipeline_v18.py" "$@"
