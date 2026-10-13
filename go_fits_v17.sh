#!/usr/bin/env bash
# Solve explicitly designated KNALDGAS FITS files with the v17 runtime.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'EOF'
Usage: go_fits_v17.sh FITS [FITS ...] [v17 native-input options]

Select one or more KNALDGAS linear RGB FITS products for solver v0.17.0.
FITS arguments may be individual paths, shell-expanded wildcards, or quoted
wildcard patterns expanded by this launcher.

Forwarded v17 options:
  --results-dir PATH
  --fits-hdu NAME_OR_INDEX
  --channel-order RGB|RGGB|RG1G2B
  --saturation-level VALUE_OR_CHANNEL_MAP
  --blind-planets

Each successful solve writes and reports these annotated products:
  astrometry_overlay.png
  report_sky_overlay.png
  solution_annotated.fits
EOF
}

if [[ $# -eq 1 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
    usage
    exit 0
fi

if [[ $# -eq 0 ]]; then
    usage >&2
    exit 2
fi

forwarded=()
input_count=0

append_fits() {
    local designation="$1"
    local -a matches=()
    if [[ "$designation" == *'*'* || "$designation" == *'?'* || "$designation" == *'['* ]]; then
        mapfile -t matches < <(compgen -G "$designation" | LC_ALL=C sort)
        if [[ ${#matches[@]} -eq 0 ]]; then
            echo "FITS wildcard matched no files: $designation" >&2
            return 2
        fi
    else
        matches=("$designation")
    fi
    local path lower
    for path in "${matches[@]}"; do
        if [[ ! -f "$path" ]]; then
            echo "FITS file does not exist: $path" >&2
            return 2
        fi
        lower="${path,,}"
        case "$lower" in
            *.fits|*.fit|*.fts|*.fits.bz2|*.fit.bz2|*.fts.bz2) ;;
            *)
                echo "Designated input is not a FITS file: $path" >&2
                return 2
                ;;
        esac
        forwarded+=("$path")
        input_count=$((input_count + 1))
    done
}

expect_value=0
after_separator=0
for argument in "$@"; do
    if [[ $after_separator -eq 1 ]]; then
        append_fits "$argument" || exit $?
        continue
    fi
    if [[ $expect_value -eq 1 ]]; then
        forwarded+=("$argument")
        expect_value=0
        continue
    fi
    case "$argument" in
        --results-dir|--fits-hdu|--channel-order|--saturation-level)
            forwarded+=("$argument")
            expect_value=1
            ;;
        --blind-planets)
            forwarded+=("$argument")
            ;;
        --)
            forwarded+=("--")
            after_separator=1
            ;;
        --version)
            if [[ $# -eq 1 ]]; then
                exec "$repo/go17.sh" --version
            fi
            echo "--version must be used alone" >&2
            exit 2
            ;;
        -*)
            echo "Unsupported go_fits_v17 option: $argument" >&2
            usage >&2
            exit 2
            ;;
        *)
            append_fits "$argument" || exit $?
            ;;
    esac
done

if [[ $expect_value -eq 1 ]]; then
    echo "Missing value for ${forwarded[-1]}" >&2
    exit 2
fi
if [[ $input_count -eq 0 ]]; then
    echo "No FITS files were supplied." >&2
    usage >&2
    exit 2
fi

capture="$(mktemp "${TMPDIR:-/tmp}/go-fits-v17.XXXXXX")"
trap 'rm -f -- "$capture"' EXIT
set +e
"$repo/go17.sh" "${forwarded[@]}" 2>&1 | tee "$capture"
status=${PIPESTATUS[0]}
set -e

while IFS= read -r analysis; do
    if [[ -f "$analysis/astrometry_overlay.png" ]]; then
        printf 'Annotated astrometry: %s\n' "$analysis/astrometry_overlay.png"
    fi
    if [[ -f "$analysis/report_sky_overlay.png" ]]; then
        printf 'Annotated sky: %s\n' "$analysis/report_sky_overlay.png"
    fi
    if [[ -f "$analysis/solution_annotated.fits" ]]; then
        printf 'Annotated FITS: %s\n' "$analysis/solution_annotated.fits"
    fi
done < <(sed -n 's/^Images and reports: //p' "$capture" | awk '!seen[$0]++')

exit "$status"
