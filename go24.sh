#!/usr/bin/env bash
# Independent v24 differential-photometry runtime.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$repo/v24/run.sh" "$@"
