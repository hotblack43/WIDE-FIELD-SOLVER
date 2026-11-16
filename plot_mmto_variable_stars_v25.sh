#!/usr/bin/env bash
# Plot v25 MMTO variable-star phase curves from the nightly extinction sidecar.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unset VIRTUAL_ENV
exec uv run --project "$repo/v25" --frozen python \
    "$repo/v25/scripts/plot_mmto_variable_stars.py" "$@"
