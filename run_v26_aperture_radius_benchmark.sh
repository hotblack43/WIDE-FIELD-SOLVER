#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")" && pwd)
unset VIRTUAL_ENV
exec uv run --project "$repo/v26" --frozen python \
  "$repo/scripts/run_v26_aperture_radius_benchmark.py" "$@"
