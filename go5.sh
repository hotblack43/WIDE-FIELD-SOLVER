#!/usr/bin/env bash
# Gaia v5 and its dependencies are committed under v5/.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v5/run.sh" "$@"
