#!/usr/bin/env bash
# Build the AGIOS Live ISO from official repositories with mkarchiso.
#
# Unprivileged preparation assembles a complete profile under .local/build/profile:
# the archiso profile from Git plus the website, the Guacamole browser client and
# the pinned guacd runtime (a squashfs made from the official Docker image).
# mkarchiso itself needs root; run the whole script as root or pass --prepare-only
# and then run the printed mkarchiso command yourself.
#
# Reproducible builds (CI, see docs/ci.md): AGIOS_ARCH_SNAPSHOT=YYYY/MM/DD takes every
# package from that day of the Arch Linux Archive instead of the host mirrorlist, and
# SOURCE_DATE_EPOCH fixes timestamps and the ISO version.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
prepare_only=false
[[ ${1:-} == --prepare-only ]] && prepare_only=true
build=.local/build
profile=$build/profile
snapshot=${AGIOS_ARCH_SNAPSHOT:-}
if [[ -n $snapshot && ! $snapshot =~ ^[0-9]{4}/[0-9]{2}/[0-9]{2}$ ]]; then
    echo "AGIOS_ARCH_SNAPSHOT must look like 2026/09/20" >&2; exit 1
fi
tools=(curl tar python rsync sha256sum)
$prepare_only || tools+=(mkarchiso)
[[ -f $build/guacd.sqfs ]] || tools+=(docker sqfstar)
for tool in "${tools[@]}"; do
    command -v "$tool" >/dev/null || { echo "Missing dependency: $tool" >&2; exit 1; }
done
mkdir -p "$build" .local out
# Guacamole 1.6.0 browser client, concatenated from the official source release.
archive=.local/guacamole-client.tar.gz
if [[ ! -f "$archive" ]]; then
    curl -fL --retry 2 https://archive.apache.org/dist/guacamole/1.6.0/source/guacamole-client-1.6.0.tar.gz -o "$archive.tmp"
    mv "$archive.tmp" "$archive"
fi
# Checksum published by Apache next to the release (guacamole-client-1.6.0.tar.gz.sha256).
echo "81f9fd5a7b4377fb0ee295d0d4fec92e9667f2aafaa3d0ed8937f535deabdee4  $archive" | sha256sum --check --quiet
tar -xzf "$archive" -C .local guacamole-client-1.6.0/guacamole-common-js guacamole-client-1.6.0/LICENSE guacamole-client-1.6.0/NOTICE
python scripts/web/prepare-assets.py
# guacd runtime: the official pinned image exported once into a read-only squashfs.
guacd_image=guacamole/guacd:1.6.0@sha256:8974eaa9ba32f713daf311e7cc8cd7e4cdfba1edea39eed75524e78ef4b08f4f
if [[ ! -f "$build/guacd.sqfs" ]]; then
    docker pull "$guacd_image"
    container=$(docker create "$guacd_image")
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
# What the Live reports as its version (web/release.py): a v* tag for releases, else "dev".
python - "$share/version.json" "${AGIOS_VERSION:-dev}" "$snapshot" <<'PY'
import json, os, re, subprocess, sys, time
path, version, snapshot = sys.argv[1:]
if version != 'dev' and not re.fullmatch(r'v\d+(\.\d+){0,2}(-[0-9A-Za-z.]+)?', version):
    sys.exit(f'AGIOS_VERSION must be a release tag like v0.1.0, not {version!r}')
revision = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip() or None
built = int(os.environ.get('SOURCE_DATE_EPOCH') or time.time())
json.dump({'version': version, 'revision': revision, 'built': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(built)),
           'arch_snapshot': snapshot or None}, open(path, 'w'), indent=2)
PY
if [[ -n $snapshot ]]; then
    # Build-time only: mkarchiso resolves packages with this file; the Live keeps its own pacman.conf.
    sed -i "s|^Include = /etc/pacman.d/mirrorlist\$|Server = https://archive.archlinux.org/repos/$snapshot/\$repo/os/\$arch|" "$profile/pacman.conf"
    grep -q "^Server = https://archive.archlinux.org/repos/$snapshot/" "$profile/pacman.conf" || { echo 'Snapshot not applied' >&2; exit 1; }
fi
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
