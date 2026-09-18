#!/usr/bin/env bash
# Gaia v8a and its dependencies are committed under v8a/.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v8a/run.sh" "$@"
