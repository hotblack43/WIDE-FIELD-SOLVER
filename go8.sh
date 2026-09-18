#!/usr/bin/env bash
# Gaia v8 and its dependencies are committed under v8/.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v8/run.sh" "$@"
