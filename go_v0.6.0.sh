#!/usr/bin/env bash
# Pinned Gaia v0.6.0, with the runtime included in this checkout.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v6/run.sh" "$@"
