#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
ARGUMENTS=("$@")
OUTPUT=""

for ((index = 0; index < ${#ARGUMENTS[@]}; index++)); do
    if [[ ${ARGUMENTS[index]} == --output ]]; then
        if ((index + 1 >= ${#ARGUMENTS[@]})); then
            printf '%s\n' "ERROR: --output needs a directory" >&2
            exit 2
        fi
        OUTPUT=${ARGUMENTS[index + 1]}
    fi
done

if [[ -n $OUTPUT ]]; then
    if [[ -d $OUTPUT ]] && [[ -n $(find "$OUTPUT" -mindepth 1 -maxdepth 1 -print -quit) ]]; then
        printf '%s\n' "ERROR: output directory is not empty: $OUTPUT" >&2
        exit 1
    fi
    if [[ -e $OUTPUT ]] && [[ ! -d $OUTPUT ]]; then
        printf '%s\n' "ERROR: output path exists and is not a directory: $OUTPUT" >&2
        exit 1
    fi
fi

exec uv run --project "$ROOT_DIR" --frozen python \
    "$ROOT_DIR/scripts/calibrate_nightly_extinction.py" "${ARGUMENTS[@]}"
