#!/usr/bin/env bash
# Launcher pinned to the Gaia-capable wide-field solver 0.8.0.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v8/run.sh" "$@"
