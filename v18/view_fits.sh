#!/usr/bin/env bash
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec uv run --project "$ROOT" --frozen python "$ROOT/point_star_fits.py" view "$@"
