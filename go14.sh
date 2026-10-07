#!/usr/bin/env bash
# Independent lunar-corroboration development runtime.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v14/run.sh" "$@"
