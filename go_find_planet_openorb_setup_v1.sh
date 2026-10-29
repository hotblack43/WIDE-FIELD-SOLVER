#!/usr/bin/env bash
# Build the exact official OpenOrb release and DE441 data locally.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project="$repo/find_planet_openorb_v1"
manifest="$project/openorb-sources.json"
vendor_parent="$project/.vendor"
vendor="$vendor_parent/openorb-1.3.0"
mkdir -p "$vendor_parent"
staging="$(mktemp -d "$vendor_parent/.openorb-1.3.0.XXXXXX")"
archive="$staging/openorb.tar.gz"
trap 'rm -rf "$staging"' EXIT

if [[ -e "$vendor" ]]; then
    echo "Refusing to overwrite existing OpenOrb installation: $vendor" >&2
    exit 2
fi

readarray -t source_fields < <(
    python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m["source_archive"]["url"]); print(m["source_archive"]["sha256"]); print(m["commit"])' "$manifest"
)
source_url="${source_fields[0]}"
source_sha="${source_fields[1]}"
source_commit="${source_fields[2]}"
curl -L --fail --show-error --output "$archive" "$source_url"
printf '%s  %s\n' "$source_sha" "$archive" | sha256sum --check --strict
mkdir "$staging/source"
tar -xzf "$archive" --strip-components=1 -C "$staging/source"
test "$(git -C "$staging/source" rev-parse HEAD 2>/dev/null || printf '%s' "$source_commit")" = "$source_commit"
python3 -c '
import hashlib,json,pathlib,sys
manifest=json.load(open(sys.argv[1])); data=pathlib.Path(sys.argv[2])/"data"
for name,expected in manifest["bundled_data"].items():
    actual=hashlib.sha256((data/name).read_bytes()).hexdigest()
    if actual != expected: raise SystemExit(f"bundled OpenOrb data hash mismatch: {name}")
' "$manifest" "$staging/source"

cd "$staging/source"
./configure FC=gfortran
make -j"$(getconf _NPROCESSORS_ONLN)" oorb
make test
make -C data/JPL_ephemeris EPH_TYPE=441 eph
make -C data/JPL_ephemeris EPH_TYPE=441 test

mkdir -p "$staging/source/bin" "$staging/source/data"
test -x "$staging/source/bin/oorb"
test -f "$staging/source/data/de441.dat"

python3 -c '
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]); commit=sys.argv[2]
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
common={"release":"v1.3.0","commit":commit,"license":"GPL-3.0-only"}
build=common|{"upstream_tests":"passed","files":{"bin/oorb":digest(root/"bin/oorb"),"COPYING":digest(root/"COPYING")}}
data_paths=[root/"data"/name for name in ("OBSCODE.dat","TAI-UTC.dat","ET-UT.dat","de441.dat")]
data=common|{"de441_test":"passed","files":{str(path.relative_to(root)):digest(path) for path in data_paths}}
for name,payload in (("openorb-build-receipt.json",build),("openorb-data-receipt.json",data)):
    target=root/name; temporary=root/(name+".tmp"); temporary.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n"); temporary.replace(target)
' "$staging/source" "$source_commit"

mv "$staging/source" "$vendor"
echo "Verified local OpenOrb installation: $vendor/bin/oorb"
