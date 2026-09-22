#!/usr/bin/env bash
# Build the AGIOS Live ISO from official repositories with mkarchiso.
#
# Unprivileged preparation assembles a complete profile under .local/build/profile:
# the archiso profile from Git plus the website, the Guacamole browser client and
# the pinned guacd runtime (a squashfs made from the official Docker image).
# mkarchiso itself needs root; run the whole script as root or pass --prepare-only
# and then run the printed mkarchiso command yourself.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
prepare_only=false
[[ ${1:-} == --prepare-only ]] && prepare_only=true
build=.local/build
profile=$build/profile
for tool in mkarchiso docker curl tar sqfstar python; do
    command -v "$tool" >/dev/null || { echo "Missing dependency: $tool" >&2; exit 1; }
done
mkdir -p "$build" .local out
# Guacamole 1.6.0 browser client, concatenated from the official source release.
archive=.local/guacamole-client.tar.gz
if [[ ! -f "$archive" ]]; then
    curl -fL --retry 2 https://archive.apache.org/dist/guacamole/1.6.0/source/guacamole-client-1.6.0.tar.gz -o "$archive.tmp"
    mv "$archive.tmp" "$archive"
fi
tar -xzf "$archive" -C .local guacamole-client-1.6.0/guacamole-common-js guacamole-client-1.6.0/LICENSE guacamole-client-1.6.0/NOTICE
python scripts/web/prepare-assets.py
# guacd runtime: the official pinned image exported once into a read-only squashfs.
if [[ ! -f "$build/guacd.sqfs" ]]; then
    docker pull guacamole/guacd:1.6.0
    container=$(docker create guacamole/guacd:1.6.0)
    docker export "$container" | sqfstar -quiet -no-progress -comp zstd "$build/guacd.sqfs.tmp"
    docker rm "$container" >/dev/null
    mv "$build/guacd.sqfs.tmp" "$build/guacd.sqfs"
fi
rm -rf "$profile"
cp -a archiso "$profile"
share=$profile/airootfs/usr/local/share/agi-os
mkdir -p "$share/web"
rsync -a --delete --exclude tests --exclude vendor --exclude __pycache__ web/ "$share/web/"
cp .local/guacamole.js "$share/web/static/guacamole.js"
cp "$build/guacd.sqfs" "$share/guacd.sqfs"
cp scripts/web/qa-guest.py "$share/qa-guest.py"
mkdir -p "$profile/airootfs/usr/share/licenses/agi-guacamole"
cp .local/guacamole-client-1.6.0/LICENSE .local/guacamole-client-1.6.0/NOTICE "$profile/airootfs/usr/share/licenses/agi-guacamole/"
git -C "$repo" rev-parse HEAD > "$share/source-revision" 2>/dev/null || true
work=$build/work
command=(mkarchiso -v -w "$repo/$work" -o "$repo/out" "$repo/$profile")
if $prepare_only || [[ $EUID -ne 0 ]]; then
    echo "Profile ready: $profile"
    echo "Run as root: ${command[*]}"
    exit 0
fi
rm -rf "$work"
"${command[@]}"
chown -R --reference="$repo/archiso" "$repo/out" "$repo/$work" 2>/dev/null || true
ls -1 "$repo"/out/agi-os-*.iso | tail -1
