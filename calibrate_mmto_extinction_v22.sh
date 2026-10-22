#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --frozen python "$ROOT/scripts/calibrate_nightly_extinction_v22.py" "$@"
