#!/usr/bin/env bash
# Independent MMTO backlog runtime based on frozen v16.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v18/run.sh" "$@"
