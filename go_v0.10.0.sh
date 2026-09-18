#!/usr/bin/env bash
# Gaia v0.10.0 and its dependencies are committed under v10/.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v10/run.sh" "$@"
