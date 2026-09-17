#!/usr/bin/env bash
# Developer entry point: boot the Live ISO, which starts its own localhost site.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec "$repo/scripts/run-live-web-vm.sh" "$@"
