#!/usr/bin/env bash
# Plot v19 MMTO variable-star time series from the nightly extinction sidecar.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unset VIRTUAL_ENV
exec uv run --project "$repo/v19" --frozen python \
    "$repo/v19/scripts/plot_mmto_variable_stars.py" "$@"
