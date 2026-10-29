#!/usr/bin/env bash
# Fit an anonymous heliocentric orbit to the controlled MMTO Object A track.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unset VIRTUAL_ENV
export PYTHONPATH="$repo/find_planet_v1${PYTHONPATH:+:$PYTHONPATH}"
exec uv run --project "$repo/find_planet_v1" --frozen python \
    -m find_planet.controlled_cli \
    --results-root "$repo/results/find-planet-v1" \
    "$@"
