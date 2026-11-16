#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")" && pwd)
unset VIRTUAL_ENV
exec uv run --project "$repo/v25" --frozen python \
  "$repo/scripts/run_v25_aperture_radius_benchmark.py" "$@"
