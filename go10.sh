#!/usr/bin/env bash
# Gaia v10 and its dependencies are committed under v10/.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v10/run.sh" "$@"
