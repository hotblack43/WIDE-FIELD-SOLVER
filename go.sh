#!/usr/bin/env bash
# Preserved Tycho-2/Hipparcos workflow. Gaia upgrades belong to go4.sh.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == --version ]]; then
    echo "Legacy Tycho-2/Hipparcos solver (preserved standalone report workflow)"
    exit 0
fi
exec "$repo/go_solve_wide.sh" "$@"
