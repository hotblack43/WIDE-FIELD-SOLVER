#!/usr/bin/env bash
# Gaia v4 and its dependencies are committed under v4/.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v4/run.sh" "$@"
