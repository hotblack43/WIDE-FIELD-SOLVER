#!/usr/bin/env bash
# Sourceable implementation for the v26 clean-clone bootstrap.

QUICKSTART_UV_VERSION="0.9.30"
QUICKSTART_UV_SHA256="8b3762374972daa7a74bbc6896cc73229ca69a07403dd9f9ea3805a51ffd7582"
QUICKSTART_UV_URL="https://github.com/astral-sh/uv/releases/download/${QUICKSTART_UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"

quickstart_error() {
    printf 'ERROR: %s\n' "$*" >&2
}

quickstart_platform() {
    local os_release="$1"
    local architecture="$2"
    local system_id=""
    local version_id=""
    local key value

    if [[ ! -r "$os_release" ]]; then
        quickstart_error "Cannot read operating-system identity: $os_release"
        quickstart_error "Supported systems: Ubuntu 24.04 or 26.04 LTS on x86-64."
        return 1
    fi
    while IFS='=' read -r key value; do
        value="${value#\"}"
        value="${value%\"}"
        case "$key" in
            ID) system_id="$value" ;;
            VERSION_ID) version_id="$value" ;;
        esac
    done < "$os_release"

    if [[ "$system_id" != "ubuntu" \
            || ( "$version_id" != "24.04" && "$version_id" != "26.04" ) \
            || "$architecture" != "x86_64" ]]; then
        quickstart_error "Supported systems: Ubuntu 24.04 or 26.04 LTS on x86-64."
        quickstart_error "Detected: ${system_id:-unknown} ${version_id:-unknown} ${architecture:-unknown}."
        return 1
    fi
}

quickstart_requirements() {
    local ca_file="$1"
    local repository_root="${2:-}"
    local -a packages=()
    local command_name

    for command_name in bash git tar sha256sum; do
        if ! command -v "$command_name" >/dev/null 2>&1; then
            case "$command_name" in
                sha256sum) packages+=(coreutils) ;;
                *) packages+=("$command_name") ;;
            esac
        fi
    done
    if ! command -v curl >/dev/null 2>&1 \
            && ! command -v wget >/dev/null 2>&1; then
        packages+=(curl)
    fi
    if [[ ! -r "$ca_file" ]]; then
        packages+=(ca-certificates)
    fi

    if (( ${#packages[@]} > 0 )); then
        quickstart_error "Missing Ubuntu bootstrap prerequisites."
        printf 'Install them with: sudo apt-get update && sudo apt-get install -y' >&2
        printf ' %s' "${packages[@]}" >&2
        printf '\n' >&2
        return 1
    fi

    if [[ -n "$repository_root" ]]; then
        local relative
        for relative in \
            v26/pyproject.toml \
            v26/uv.lock \
            v26/demo.sh \
            v26/scripts/run_mmto_demo.py \
            v26/examples/mmto/2026_09_19__02_20_01.fits.bz2 \
            v26/examples/mmto/baseline.json \
            v26/data/stars_gaia_dr3_g75.csv \
            v26/data/sky_masks/mmto_installation_2026a.json; do
            if [[ ! -f "$repository_root/$relative" ]]; then
                quickstart_error "Required v26 release file is missing: $relative"
                return 1
            fi
        done
    fi
}

quickstart_fetch() {
    local url="$1"
    local destination="$2"
    if command -v curl >/dev/null 2>&1; then
        curl --proto '=https' --tlsv1.2 --fail --location \
            --silent --show-error --output "$destination" "$url"
    else
        wget --https-only --secure-protocol=TLSv1_2 --quiet \
            --output-document="$destination" "$url"
    fi
}

quickstart_install_uv() (
    set -u
    local repository_root="$1"
    local final_dir="$repository_root/.tools/uv/$QUICKSTART_UV_VERSION"
    local final_binary="$final_dir/uv"
    local version_output

    if [[ -x "$final_binary" ]]; then
        version_output="$($final_binary --version 2>/dev/null)" || {
            quickstart_error "Existing local uv is not executable: $final_binary"
            return 1
        }
        if [[ "$version_output" != "uv $QUICKSTART_UV_VERSION" ]]; then
            quickstart_error "Existing local uv has the wrong version: $version_output"
            return 1
        fi
        printf '%s\n' "$final_binary"
        return 0
    fi

    mkdir -p "$repository_root/.tools"
    local temporary
    temporary="$(mktemp -d "$repository_root/.tools/.uv-install.XXXXXX")" || return 1
    local archive="$temporary/uv.tar.gz"
    local unpacked="$temporary/unpacked"
    local downloaded_sha256

    printf 'Downloading pinned uv %s...\n' "$QUICKSTART_UV_VERSION" >&2
    if ! quickstart_fetch "$QUICKSTART_UV_URL" "$archive"; then
        quickstart_error "Could not download pinned uv $QUICKSTART_UV_VERSION."
        rm -rf "$temporary"
        return 1
    fi
    downloaded_sha256="$(sha256sum "$archive")"
    downloaded_sha256="${downloaded_sha256%% *}"
    if [[ "$downloaded_sha256" != "$QUICKSTART_UV_SHA256" ]]; then
        quickstart_error "Downloaded uv archive checksum does not match the reviewed release."
        rm -rf "$temporary"
        return 1
    fi

    mkdir -p "$unpacked"
    if ! tar -xzf "$archive" -C "$unpacked"; then
        quickstart_error "The verified uv archive could not be extracted."
        rm -rf "$temporary"
        return 1
    fi
    local candidate="$unpacked/uv-x86_64-unknown-linux-gnu/uv"
    if [[ ! -f "$candidate" ]]; then
        quickstart_error "The verified uv archive does not contain the expected executable."
        rm -rf "$temporary"
        return 1
    fi
    chmod 0755 "$candidate"
    version_output="$($candidate --version 2>/dev/null)" || {
        quickstart_error "The verified uv executable did not start."
        rm -rf "$temporary"
        return 1
    }
    if [[ "$version_output" != "uv $QUICKSTART_UV_VERSION" ]]; then
        quickstart_error "The verified archive reported an unexpected uv version: $version_output"
        rm -rf "$temporary"
        return 1
    fi

    mkdir -p "$final_dir"
    local staged="$final_dir/.uv.$$"
    mv "$candidate" "$staged"
    chmod 0755 "$staged"
    mv -f "$staged" "$final_binary"
    rm -rf "$temporary"
    printf '%s\n' "$final_binary"
)

quickstart_sync() {
    local repository_root="$1"
    local uv_binary="$2"
    "$uv_binary" sync --project "$repository_root/v26" --frozen --python 3.12
}

quickstart_demo() {
    local repository_root="$1"
    local uv_binary="$2"
    local output="$3"
    PATH="${uv_binary%/*}:$PATH" \
        "$repository_root/v26/demo.sh" --output "$output"
}

quickstart_main() {
    local repository_root="$1"
    shift
    if (( $# != 0 )); then
        quickstart_error "quickstart.sh takes no arguments."
        return 2
    fi

    quickstart_platform /etc/os-release "$(uname -m)" || return $?
    quickstart_requirements \
        /etc/ssl/certs/ca-certificates.crt "$repository_root" || return $?

    local uv_binary
    uv_binary="$(quickstart_install_uv "$repository_root")" || return $?
    export UV_CACHE_DIR="$repository_root/.tools/cache"
    export UV_PYTHON_INSTALL_DIR="$repository_root/.tools/python"
    export UV_PROJECT_ENVIRONMENT="$repository_root/v26/.venv"
    export UV_MANAGED_PYTHON=1
    unset VIRTUAL_ENV
    export PATH="${uv_binary%/*}:$PATH"

    printf 'Preparing the locked v26 environment...\n'
    quickstart_sync "$repository_root" "$uv_binary" || return $?

    local output="$repository_root/results/quickstart-v26"
    printf 'Running the bundled v26 verification...\n'
    quickstart_demo "$repository_root" "$uv_binary" "$output" || return $?

    local report="$output/report.pdf"
    if [[ ! -f "$report" ]]; then
        quickstart_error "The demonstration completed without its expected report.pdf: $report"
        return 1
    fi

    printf '\nQuick start complete.\n'
    printf 'Report: %s\n' "$report"
    printf 'Your image: ./go25.sh /full/path/to/image.fits\n'
}
