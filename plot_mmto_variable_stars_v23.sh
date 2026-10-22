#!/usr/bin/env bash
# Plot v23 MMTO variable-star time series from the nightly extinction sidecar.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unset VIRTUAL_ENV
exec uv run --project "$repo/v23" --frozen python \
    "$repo/v23/scripts/plot_mmto_variable_stars.py" "$@"
