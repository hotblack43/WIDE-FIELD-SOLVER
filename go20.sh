#!/usr/bin/env bash
# Independent v20 bounded-backward MMTO runtime.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v20/run.sh" "$@"
