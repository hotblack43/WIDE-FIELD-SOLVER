#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")" && pwd)"
exec env -u VIRTUAL_ENV uv run --project "$repo" --frozen python "$repo/analyse_image.py" "$@"
