#!/usr/bin/env bash
# Current convenience launcher; use the versioned filename to pin a release.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/go_v0.4.0.sh" "$@"
