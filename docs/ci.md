# Continuous integration and reproducible ISO builds

Two GitHub Actions workflows live in `.github/workflows/`.

| Workflow | Triggers | What it does |
|---|---|---|
| `tests.yml` | every pull request, push to `main`, manual, called by `iso.yml` | Installer and website unit tests, `node --check` of the browser scripts, `bash -n` of the scripts and a Python syntax pass, inside the pinned Arch Linux container with packages from the pinned snapshot (the same Python and aiohttp as in the Live image). |
| `iso.yml` | push to `main`, tag `v*`, manual, pull requests that touch `archiso/`, `web/`, `scripts/build-iso.sh`, `scripts/ci/`, `scripts/web/` or the workflow | Unit tests first (mandatory), then the ISO build, the sha256 file, a smoke boot in QEMU with UEFI and with BIOS, and artifacts. A `v*` tag also publishes a GitHub release. |

Every third-party action is pinned to a commit; `tests/test_ci.py` fails when a
new `uses:` line is not.

## Reproducible build

`scripts/ci/build-iso.sh` is the single entry point for CI and for local
reproduction. The host needs Docker plus the unprivileged preparation tools of
`scripts/build-iso.sh` (curl, tar, python, rsync, and sqfstar for the first
guacd export); `mkarchiso` runs inside a privileged container.

- **Container:** `archlinux:base-devel-<date>` pinned by digest in
  `scripts/ci/build-iso.sh` and `.github/workflows/tests.yml` (a test keeps the
  two in one version).
- **Packages:** `scripts/ci/arch-snapshot` holds one day of the
  [Arch Linux Archive](https://archive.archlinux.org/repos/) (`YYYY/MM/DD`). The
  container is synchronized to that day with `pacman -Syuu` (so `archiso` itself
  is pinned), and `AGIOS_ARCH_SNAPSHOT` makes `scripts/build-iso.sh` point the
  profile's build-time `pacman.conf` at the same day. The Live keeps its own
  `pacman.conf` and mirror list; the snapshot only affects what goes into the image.
- **Time:** `SOURCE_DATE_EPOCH` defaults to the commit time, so the ISO version and
  file name (`agi-os-YYYY.MM.DD-x86_64.iso`) come from the commit, and mkarchiso
  and squashfs timestamps are fixed.
- **Other inputs:** the Guacamole client tarball is checked against the sha256
  published by Apache; the guacd image is pinned by digest.
- **Outputs in `out/`:** the ISO, `<iso>.sha256` and `build-info.json` (size,
  checksum, source revision, snapshot, container image, `SOURCE_DATE_EPOCH`).

Local reproduction of a CI build of the same commit:

```sh
scripts/ci/build-iso.sh                  # out/ must not contain an older ISO
AGIOS_ARCH_SNAPSHOT=2026/09/22 scripts/ci/build-iso.sh   # try a newer package set
```

`AGIOS_WORK_DIR` moves the ~8 GB mkarchiso work tree (CI uses `/mnt`), and
`AGIOS_BUILD_IMAGE` overrides the container.

Moving to newer packages is a deliberate change: bump the date in
`scripts/ci/arch-snapshot` (and, when useful, the container tag and digest) in
its own commit, and let `iso.yml` build and smoke-boot it. The archive keeps
every day, so old commits stay rebuildable.

## Smoke boot

`scripts/ci/smoke-boot.py ISO --firmware uefi|bios` boots the ISO headless with
the test fw_cfg marker and the private QA serial port, exactly as the test stand
does, and passes when the Live's QA agent answers, `agi-guacd`, `agi-web` and the
display manager are active, `GET /api/state` returns JSON and (with
`--expect-revision`) the image carries the expected source revision. It uses KVM
when `/dev/kvm` is usable and falls back to TCG with a longer timeout. On failure
it saves a screenshot (`screen.ppm`), the QEMU log and `result.json` in `--logs`;
CI uploads them as the `smoke-boot-logs` artifact. The script needs no stand lock
in CI; on the shared development host treat it like any other QEMU run.

With KVM a boot takes about 40 s (BIOS) to 110 s (UEFI) locally.

## Runners

By default `iso.yml` uses GitHub-hosted `ubuntu-24.04`: it frees disk space, enables
`/dev/kvm` through a udev rule and installs QEMU, OVMF and squashfs-tools. To use a
self-hosted runner with KVM, set the repository variable `AGIOS_ISO_RUNNER` to its
label; that runner needs Docker (privileged containers), QEMU, `qemu-img`, OVMF,
Python 3, rsync and squashfs-tools, and ~15 GB free disk.

## Releases

Pushing a tag `v*` runs the whole pipeline and then publishes a GitHub release
named after the tag with the ISO, its `.sha256` and `build-info.json`; the notes
come from `scripts/ci/changelog.sh` (build facts and the commits since the previous
`v*` tag). GitHub release assets must be smaller than 2 GiB; the build fails
early if the ISO grows past that. Signing the ISO and the checksum is tracked
separately (CMP-125) and is not part of this pipeline yet.
