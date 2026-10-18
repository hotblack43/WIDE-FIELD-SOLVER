#!/usr/bin/env bash
# Independent v21 bounded-backward MMTO runtime.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v21/run.sh" "$@"
