#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$ROOT/v26" --frozen python \
  "$ROOT/scripts/calibrate_nightly_extinction_v26.py" "$@"
