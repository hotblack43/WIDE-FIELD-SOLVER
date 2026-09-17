#!/usr/bin/env bash
# Gaia v7 and its dependencies are committed under v7/.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v7/run.sh" "$@"
