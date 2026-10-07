#!/usr/bin/env bash
# Read saved MMTO photometry using the independent v8a Python environment.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec env -u VIRTUAL_ENV uv run --project "$repo/v8a" --frozen python "$repo/scripts/plot_star_lightcurves.py" "$@"
