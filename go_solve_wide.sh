#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "$0")" && pwd)"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 IMAGE_FILE" >&2
    exit 2
fi

image="$1"
if [[ ! -f "$image" ]]; then
    echo "Image file does not exist: $image" >&2
    exit 2
fi

filename="$(basename "$image")"
stem="${filename%.*}"
output="$repo/results/$stem"

"$repo/analyse.sh" "$image" --output "$output"

report="$(find "$output" -maxdepth 1 -type f -name 'report_*.pdf' -print -quit)"
if [[ -z "$report" ]]; then
    echo "Analysis finished without a report PDF in $output" >&2
    exit 1
fi

echo "Report: $report"
