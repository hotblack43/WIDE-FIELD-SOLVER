#!/usr/bin/env bash
set -euo pipefail
PLOT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --project "$PLOT_ROOT" --frozen python "$PLOT_ROOT/scripts/plot_things_1.py" --overwrite "$@"
