#!/usr/bin/env bash
# Independent v23 differential-photometry runtime.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v23/run.sh" "$@"
