#!/usr/bin/env bash
# Operate the complete v25 visible-sky calibration lifecycle.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unset VIRTUAL_ENV
exec uv run --project "$repo/v25" --frozen python \
    "$repo/v25/visible_sky_operator.py" "$@"
