#!/usr/bin/env bash
# Process new verified MMTO images with v11, then regenerate photometry products.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$repo" --frozen python \
    "$repo/scripts/run_mmto_photometry_pipeline.py" "$@"
