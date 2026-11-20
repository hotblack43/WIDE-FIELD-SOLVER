#!/usr/bin/env bash
set -euo pipefail
repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$repository_root/v25/scripts/quickstart.sh"
quickstart_main "$repository_root" "$@"
