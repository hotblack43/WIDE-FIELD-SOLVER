#!/usr/bin/env bash
# Latest v4 launcher; the original go.sh keeps its established version.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/go_v0.4.1.sh" "$@"
