#!/usr/bin/env bash
# Independent radial-model comparison development runtime.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v12/run.sh" "$@"
