#!/usr/bin/env bash
# Independent v26 differential-photometry runtime.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v26/run.sh" "$@"
