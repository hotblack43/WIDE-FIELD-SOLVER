#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$script_dir/v11/pyproject.toml" ]]; then
  project_dir="$script_dir/v11"
else
  project_dir="$script_dir"
fi
exec uv run --project "$project_dir" --frozen python "$project_dir/scripts/run_mmto_demo.py" "$@"
