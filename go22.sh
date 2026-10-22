#!/usr/bin/env bash
# Independent v22 differential-photometry runtime.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v22/run.sh" "$@"
