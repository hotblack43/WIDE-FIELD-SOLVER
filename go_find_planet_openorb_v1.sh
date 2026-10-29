#!/usr/bin/env bash
# Run the identity-neutral OpenOrb workflow from its independent frozen runtime.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project="$repo/find_planet_openorb_v1"
unset VIRTUAL_ENV
exec uv run --project "$project" --frozen python -m find_planet_openorb.cli \
    --vendor-root "$project/.vendor/openorb-1.3.0" \
    --sources-manifest "$project/openorb-sources.json" \
    --results-root "$repo/results/find-planet-openorb-v1" \
    "$@"
