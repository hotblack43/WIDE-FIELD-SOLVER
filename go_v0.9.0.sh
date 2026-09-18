#!/usr/bin/env bash
# Gaia v0.9.0 and its dependencies are committed under v9/.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v9/run.sh" "$@"
