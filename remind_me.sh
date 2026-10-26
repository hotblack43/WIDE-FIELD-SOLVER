#!/usr/bin/env bash
# List the newest available v23 plots, retaining older stage products as fallbacks.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
exec python3 "$repo/scripts/remind_me.py" "$@"
