#!/usr/bin/env bash
# Independent v25 differential-photometry runtime.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v25/run.sh" "$@"
