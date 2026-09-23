#!/usr/bin/env bash
# Reproducible AGIOS Live ISO build in a privileged Arch Linux container.
#
# WARNING: for CI runners and disposable build VMs only. A privileged container shares
# the host's devices; never run this on a developer workstation. It refuses to start
# unless CI=true (set by GitHub Actions) or AGIOS_ALLOW_PRIVILEGED_BUILD=1.
#
# The host needs Docker, curl, tar, python, rsync and sqfstar (only for the first guacd
# export); mkarchiso and pacman run inside the pinned container. Every package, the
# container's own archiso included, comes from one day of the Arch Linux Archive
# (scripts/ci/arch-snapshot), and SOURCE_DATE_EPOCH defaults to the commit time, so
# the same commit gives the same package set, timestamps and ISO version.
#
#   scripts/ci/build-iso.sh                 # ISO, .sha256 and build-info.json in out/
#
# Environment: AGIOS_ARCH_SNAPSHOT=YYYY/MM/DD overrides the pinned snapshot,
# AGIOS_BUILD_IMAGE the container image, AGIOS_WORK_DIR the mkarchiso work directory
# (needs ~8 GB), SOURCE_DATE_EPOCH the build time.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$repo"
image_default=archlinux:base-devel-20260920.0.596911@sha256:8745817f349ed24373341ddb92776209eeec3f0364ea48f7f645ac5800d30a50

if [[ ${1:-} != --inside && ${CI:-} != true && ${AGIOS_ALLOW_PRIVILEGED_BUILD:-} != 1 ]]; then
    echo 'Refusing to run a privileged container outside CI; see the warning at the top of this script.' >&2
    exit 1
fi

if [[ ${1:-} == --inside ]]; then
    # Runs as root in the container: /src is the repository, /work the scratch space.
    [[ -f /.dockerenv ]] || { echo '--inside is only for the build container' >&2; exit 1; }
    snapshot=$AGIOS_ARCH_SNAPSHOT
    echo "Server = https://archive.archlinux.org/repos/$snapshot/\$repo/os/\$arch" > /etc/pacman.d/mirrorlist
    # -uu also downgrades the image to the snapshot, so mkarchiso itself is pinned.
    pacman -Syuu --noconfirm --needed archiso git python rsync
    git config --global --add safe.directory /src
    rm -rf /work/*
    mkarchiso -v -w /work -o /src/out /src/.local/build/profile
    rm -rf /work/*
    exit 0
fi

snapshot=${AGIOS_ARCH_SNAPSHOT:-$(tr -d '[:space:]' < scripts/ci/arch-snapshot)}
image=${AGIOS_BUILD_IMAGE:-$image_default}
work=${AGIOS_WORK_DIR:-$repo/.local/build/work}
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git log -1 --format=%ct)}
export AGIOS_ARCH_SNAPSHOT=$snapshot SOURCE_DATE_EPOCH
command -v docker >/dev/null || { echo 'Missing dependency: docker' >&2; exit 1; }
AGIOS_ARCH_SNAPSHOT=$snapshot ./scripts/build-iso.sh --prepare-only
mkdir -p out "$work"
shopt -s nullglob
before=(out/agi-os-*.iso)
((${#before[@]} == 0)) || { echo "out/ already has ISO images; move them away first" >&2; exit 1; }
docker run --rm --privileged \
    -e AGIOS_ARCH_SNAPSHOT -e SOURCE_DATE_EPOCH \
    -v "$repo:/src" -v "$work:/work" -w /src \
    "$image" bash /src/scripts/ci/build-iso.sh --inside
# Files written by root in the container are handed back to the invoking user.
docker run --rm -v "$repo/out:/out" -v "$work:/work" "$image" \
    chown -R "$(id -u):$(id -g)" /out /work
isos=(out/agi-os-*.iso)
((${#isos[@]} == 1)) || { echo "Expected one ISO in out/, found ${#isos[@]}" >&2; exit 1; }
iso=${isos[0]}
(cd out && sha256sum "$(basename "$iso")" > "$(basename "$iso").sha256")
python - "$iso" "$snapshot" "$image" <<'PY'
import json, os, subprocess, sys
from pathlib import Path
iso, snapshot, image = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
revision = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
info = {'iso': iso.name, 'size': iso.stat().st_size,
        'sha256': (iso.parent / (iso.name + '.sha256')).read_text().split()[0],
        'source_revision': revision, 'source_date_epoch': int(os.environ['SOURCE_DATE_EPOCH']),
        'arch_snapshot': snapshot, 'build_image': image}
(iso.parent / 'build-info.json').write_text(json.dumps(info, indent=2) + '\n')
print(json.dumps(info, indent=2))
PY
