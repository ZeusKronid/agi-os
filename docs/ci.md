# Continuous integration and reproducible ISO builds

Two GitHub Actions workflows live in `.github/workflows/`.

| Workflow | Triggers | What it does |
|---|---|---|
| `tests.yml` | every pull request, push to `main`, manual, called by `iso.yml` | Installer and website unit tests, `node --check` of the browser scripts, `bash -n` of the scripts and a Python syntax pass, inside the pinned Arch Linux container with packages from the pinned snapshot (the same Python and aiohttp as in the Live image). |
| `iso.yml` | push to `main`, tag `v*`, manual, pull requests that touch `archiso/`, `web/`, `scripts/build-iso.sh`, `scripts/ci/`, `scripts/web/` or the workflow | Unit tests first (mandatory), then the ISO build, the sha256 file, a smoke boot in QEMU with UEFI and with BIOS, and artifacts. A `v*` tag also publishes a GitHub release. |

Unit tests run as an ordinary user in the container, as on a developer machine.
A pull request that changes the image runs the unit tests twice (`tests.yml`
directly and through `iso.yml`); that costs about two minutes and keeps the ISO
job gated by tests for every trigger. The ISO job's summary shows the ISO size
against the 2 GiB release limit, so growth is visible before it breaks releases.

Every third-party action is pinned to a commit; `tests/test_ci.py` fails when a
new `uses:` line is not.

## Reproducible build

`scripts/ci/build-iso.sh` is the single entry point for CI and for reproducing a
CI build. The host needs Docker plus the unprivileged preparation tools of
`scripts/build-iso.sh` (curl, tar, python, rsync, and sqfstar for the first
guacd export); `mkarchiso` runs inside a privileged container.

> **Only on CI runners or a disposable build VM.** A privileged container shares
> the host's devices, so running it on a developer workstation can disturb the
> desktop session. The script refuses to start unless `CI=true` (GitHub Actions)
> or `AGIOS_ALLOW_PRIVILEGED_BUILD=1` is set. On a workstation build with
> `scripts/build-iso.sh` as described in the README instead.

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
- **Release signing:** the `release` job adds `SHA256SUMS`, detached OpenPGP
  signatures and the public key (`scripts/release/sign-iso.py`); see
  [Download and verify](download.md) for the key settings and how users verify.

Reproducing a CI build of the same commit on a disposable build VM:

```sh
AGIOS_ALLOW_PRIVILEGED_BUILD=1 scripts/ci/build-iso.sh   # out/ must not contain an older ISO
AGIOS_ALLOW_PRIVILEGED_BUILD=1 AGIOS_ARCH_SNAPSHOT=2026/09/22 scripts/ci/build-iso.sh
```

The same package set without a container: `AGIOS_ARCH_SNAPSHOT=$(cat scripts/ci/arch-snapshot)
SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) scripts/build-iso.sh --prepare-only`, then
`mkarchiso` as root (the host's own archiso version is then not pinned).

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
label; that runner needs Docker (privileged containers, also used once to export
the pinned guacd image), QEMU, `qemu-img`, OVMF, Python 3 as `python`, rsync,
squashfs-tools 4.6 or newer (`sqfstar`), `/dev/kvm` and ~15 GB free disk. Such a
runner must be a dedicated build machine, not someone's workstation.

## Versions and the update check

`scripts/build-iso.sh` writes `/usr/local/share/agi-os/version.json` into the image:
`version` is the release tag (`AGIOS_VERSION`, set by `iso.yml` for `v*` tags) or
`dev` for every other build, plus the source revision, the build time
(`SOURCE_DATE_EPOCH`) and the Arch snapshot. The website shows it at the bottom of
the page (`GET /api/version`, `web/release.py`), and the smoke boot checks that the
Live reports the expected version.

«Проверить обновления» (`POST /api/version/check`) asks
`https://api.github.com/repos/ZeusKronid/agi-os/releases/latest` for the latest
published release **only when the user presses the button**; the Live never
contacts the release server on its own. The answer is reduced to the version,
date, release notes (bounded) and links that stay on `github.com`. A release build
compares versions (`v1.2.3`, pre-releases like `v1.2.3-rc.1` sort first); a `dev`
build only names the latest release. Verifying and writing the new ISO is on the
download page; the Live does not download or apply anything itself.

## Releases

Pushing a tag `v*` runs the whole pipeline and then publishes a GitHub release
named after the tag with the ISO, its `.sha256`, `build-info.json`, `SHA256SUMS`,
detached signatures, and the public signing key. The notes come from
`scripts/ci/changelog.sh` (build facts and the commits since the previous `v*`
tag). The release job verifies the checksum and signatures before publication.
GitHub release assets must be smaller than 2 GiB; the build fails early if the
ISO grows past that. See [Download and verify](download.md) for the fingerprint.
