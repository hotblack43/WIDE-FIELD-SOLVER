#!/usr/bin/env bash
# Plot v26 MMTO variable-star phase curves from the nightly extinction sidecar.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unset VIRTUAL_ENV
exec uv run --project "$repo/v26" --frozen python \
    "$repo/v26/scripts/plot_mmto_variable_stars.py" "$@"
