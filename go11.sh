#!/usr/bin/env bash
# Independent joint stellar/planetary development runtime.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v11/run.sh" "$@"
