#!/usr/bin/env bash
# Extract repeated-star photometry from the run database and regenerate its plots.
set -euo pipefail

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec uv run --project "$repo" --frozen python \
    "$repo/scripts/plot_repeated_star_colours.py" \
    --database "$repo/results/stars.sqlite" \
    --gaia-catalogue "$repo/v7/data/stars_gaia_dr3_g75.gaia-source.csv" \
    --output "$repo/results/subaru-repeated-star-colours" \
    "$@"
