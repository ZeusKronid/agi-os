#!/usr/bin/env bash
# Release notes for tag TAG: build facts from build-info.json and the commits since
# the previous v* tag (all history for the first release). Prints Markdown.
#   scripts/ci/changelog.sh v0.1.0 out/build-info.json > out/CHANGELOG.md
set -euo pipefail
tag=${1:?tag}
info=${2:?build-info.json}
previous=$(git describe --tags --abbrev=0 --match 'v*' "$tag^" 2>/dev/null || true)
python3 - "$tag" "$info" "$previous" <<'PY'
import json, sys
tag, info, previous = sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3]
print(f"# AGIOS {tag}\n")
print(f"- ISO: `{info['iso']}` ({info['size'] / 2**30:.2f} GiB)")
print(f"- SHA-256: `{info['sha256']}`")
print(f"- Source: `{info['source_revision']}`")
print(f"- Arch Linux Archive snapshot: `{info['arch_snapshot']}`")
print(f"- Build container: `{info['build_image']}`, SOURCE_DATE_EPOCH={info['source_date_epoch']}\n")
print("Verify the download: `sha256sum --check " + info['iso'] + ".sha256`\n")
print(f"## Changes since {previous}\n" if previous else "## Changes\n")
PY
range=$tag
[[ -n $previous ]] && range=$previous..$tag
git log --no-merges --format='- %s (%h)' "$range"
