#!/usr/bin/env bash
# Build the user-facing Live ISO and its inner installer without host root.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
base=${1:-}
if [[ -z "$base" ]]; then
    shopt -s nullglob
    images=(out/agi-os-desktop-*-x86_64.iso)
    ((${#images[@]})) || { echo 'Build the desktop ISO first (see README).'; exit 1; }
    base=${images[${#images[@]}-1]}
fi
for tool in uv docker xorriso unsquashfs mksquashfs curl tar bsdtar pacman python; do
    command -v "$tool" >/dev/null || { echo "Missing dependency: $tool"; exit 1; }
done
mkdir -p .local/web-iso
[[ -x .local/venv/bin/python ]] || uv venv .local/venv
uv pip install --python .local/venv/bin/python -r web/requirements.txt
docker pull guacamole/guacd:1.6.0
archive=.local/guacamole-client.tar.gz
if [[ ! -f "$archive" ]]; then
    curl -fL --retry 2 https://archive.apache.org/dist/guacamole/1.6.0/source/guacamole-client-1.6.0.tar.gz -o "$archive.tmp"
    mv "$archive.tmp" "$archive"
fi
tar -xzf "$archive" -C .local guacamole-client-1.6.0/guacamole-common-js guacamole-client-1.6.0/LICENSE guacamole-client-1.6.0/NOTICE
python scripts/web/prepare-assets.py
python scripts/web/prepare-iso.py "$base"
if [[ ! -f .local/live-payload/guacd-rootfs.tar ]]; then
    mkdir -p .local/live-payload
    container=$(docker create guacamole/guacd:1.6.0)
    docker export "$container" -o .local/live-payload/guacd-rootfs.tar
    docker rm "$container" >/dev/null
fi
python scripts/web/prepare-live-iso.py --base "$base"
echo 'Ready. Boot out/agi-os-live-web.iso, or test with ./scripts/run-live-web-vm.sh'
