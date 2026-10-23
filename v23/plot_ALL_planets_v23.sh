#!/usr/bin/env bash
# Preserve failed v23 planet products and retry transient Horizons failures.
set -uo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
MAX_ATTEMPTS=4
RETRY_DELAY=${V23_HORIZONS_RETRY_DELAY_SECONDS:-1}
OUTPUT=""
arguments=("$@")

if [[ ! $RETRY_DELAY =~ ^[0-9]+$ ]]; then
    printf '%s\n' "ERROR: V23_HORIZONS_RETRY_DELAY_SECONDS must be a nonnegative integer" >&2
    exit 2
fi

for ((index = 0; index < ${#arguments[@]}; ++index)); do
    if [[ ${arguments[index]} == --output ]]; then
        ((index + 1 < ${#arguments[@]})) || {
            printf '%s\n' "ERROR: --output needs a directory" >&2
            exit 2
        }
        OUTPUT=${arguments[index + 1]}
    fi
done

if [[ -z $OUTPUT ]]; then
    printf '%s\n' "ERROR: the v23 planet retry launcher requires --output DIR" >&2
    exit 2
fi
if [[ -e $OUTPUT ]]; then
    printf '%s\n' "ERROR: output path already exists: $OUTPUT" >&2
    exit 1
fi

is_transient_horizons_failure() {
    local log=$1
    [[ -f $log ]] || return 1
    grep -Eq \
        'requests\.exceptions\.(ConnectTimeout|ReadTimeout|ConnectionError)|urllib3\.exceptions\.(ConnectTimeoutError|ReadTimeoutError|ProtocolError)|requests\.exceptions\.HTTPError:.* (408|425|429|500|502|503|504) (Client|Server) Error|HTTP (408|425|429|500|502|503|504)' \
        "$log"
}

for ((attempt = 1; attempt <= MAX_ATTEMPTS; ++attempt)); do
    failed="${OUTPUT}-failed-attempt-${attempt}"
    if [[ -e $OUTPUT || -e $failed ]]; then
        printf '%s\n' "ERROR: planet output or retry evidence path already exists: $OUTPUT or $failed" >&2
        exit 1
    fi

    printf 'V23 planet plotting attempt %d/%d\n' "$attempt" "$MAX_ATTEMPTS"
    "$ROOT_DIR/v23/plot_ALL_planets_impl_v23.sh" \
        --include-uncalibrated "${arguments[@]}"
    status=$?
    if ((status == 0)); then
        if [[ ! -d $OUTPUT ]]; then
            printf 'ERROR: planet plotting exited successfully without output: %s\n' \
                "$OUTPUT" >&2
            exit 1
        fi
        printf 'V23 planet plotting complete: %s\n' "$OUTPUT"
        exit 0
    fi

    if [[ -e $OUTPUT ]] && ! mv -T -- "$OUTPUT" "$failed"; then
        printf 'ERROR: could not preserve failed planet output at %s\n' "$failed" >&2
        exit 1
    fi
    if ! is_transient_horizons_failure "$failed/plot_ALL_planets.log"; then
        printf 'ERROR: non-transient planet plotting failure; preserved at %s\n' \
            "$failed" >&2
        exit "$status"
    fi
    if ((attempt == MAX_ATTEMPTS)); then
        printf 'ERROR: transient Horizons failure persisted for %d attempts; last evidence: %s\n' \
            "$MAX_ATTEMPTS" "$failed" >&2
        exit "$status"
    fi
    delay=$((RETRY_DELAY * (2 ** (attempt - 1))))
    ((delay <= 16)) || delay=16
    printf 'Transient Horizons failure preserved at %s; retrying in %d seconds\n' \
        "$failed" "$delay" >&2
    sleep "$delay"
done
