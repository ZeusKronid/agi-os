#!/usr/bin/env bash
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python "$repo_dir/archiso/airootfs/usr/local/share/agi-os/installer/app.py" "$@"
