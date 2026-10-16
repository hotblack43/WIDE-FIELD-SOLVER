#!/usr/bin/env bash
# Independent v19 MMTO variable-star development runtime.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v19/run.sh" "$@"
