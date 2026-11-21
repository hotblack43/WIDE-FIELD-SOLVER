#!/usr/bin/env bash
# Operate the complete v26 visible-sky calibration lifecycle.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
unset VIRTUAL_ENV
exec uv run --project "$repo/v26" --frozen python \
    "$repo/v26/visible_sky_operator.py" "$@"
