#!/usr/bin/env bash
# Fit planet-only nightly empirical extinction and generate its diagnostics.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec env -u VIRTUAL_ENV uv run --project "$repo" --frozen python \
    "$repo/scripts/plot_planet_only_airmass_correction.py" "$@"
