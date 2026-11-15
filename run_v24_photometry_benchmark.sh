#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")" && pwd)
unset VIRTUAL_ENV
exec uv run --project "$repo/v24" --frozen python \
  "$repo/scripts/run_v24_photometry_benchmark.py" "$@"

