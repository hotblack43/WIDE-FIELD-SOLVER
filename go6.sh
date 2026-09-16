#!/usr/bin/env bash
# Gaia v6 and its dependencies are committed under v6/.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v6/run.sh" "$@"
