# AGIOS

AGIOS boots from a **Live ISO** and opens `http://localhost:8787` in Firefox
inside the Live environment. You describe the system you want to an agent,
review the configuration, and the installer builds it **as a preview**. A
virtual machine inside Live shows the resulting system through **Apache
Guacamole** on the website. Where you place the preview determines whether a
disk is changed before final installation: the RAM option leaves disks alone,
while file and partition options use the storage you choose. You can discard
the preview and reverse supported storage changes; erasing a disk is
irreversible.

```text
Computer (or an external test VM during development)
└─ AGIOS Live
   ├─ Firefox → localhost:8787 → agent and controller
   ├─ Preview: QEMU + Guacamole → installed system
   │    stored in memory (zram), in a file on any drive,
   │    or in a temporary partition — your choice, with rollback where supported
   └─ Finalization → computer disk (BIOS/UEFI, LUKS, zram swap)
```

## Download

The latest tested build from `main` is available in the
[Live ISO workflow](https://github.com/ZeusKronid/agi-os/actions/workflows/iso.yml?query=branch%3Amain):
open a successful run and download the **agi-os-iso** artifact. Extract the ZIP
to get the ISO, its `.sha256` file, and `build-info.json`. GitHub requires you
to sign in to download Actions artifacts, and these builds expire after seven
days. Check the image after extraction:

```sh
sha256sum --check agi-os-*.iso.sha256
```

Versioned, signed images are published on the
[Releases page](https://github.com/ZeusKronid/agi-os/releases) from `v*` tags.
The AGIOS release key fingerprint is
`BA1D BAF6 09C7 6719 47DD A5E4 D1DF F581 C1F8 77D3`; the
[public key](docs/agios-release-key.asc) is also in this repository. See
[download and verification](docs/download.md) before using a release image.

## Build

```sh
sudo ./scripts/build-iso.sh          # or --prepare-only, then run mkarchiso as root
```

A single ISO (`out/agi-os-<date>-x86_64.iso`, about 2 GB) is built by
`mkarchiso` from the official `core` and `extra` repositories with package
signature verification. The image includes the website, the Guacamole 1.6.0
client from its official source release, and `guacd` from the pinned
`guacamole/guacd:1.6.0` image (squashfs, started with `RootImage=`). The
preview VM boots from the same media without a graphical desktop, so it does
not need a second image. The build does not use the host's package cache or
packages optimized for a particular CPU.

For reproducible CI builds, `scripts/ci/build-iso.sh` runs `mkarchiso` in a
pinned, privileged Arch container (for CI or a disposable build VM, not a
workstation). Packages come from one day of the Arch Linux Archive, specified
in `scripts/ci/arch-snapshot`, and `SOURCE_DATE_EPOCH` is set to the commit
time. CI places a `.sha256` file and `build-info.json` next to the ISO. GitHub
Actions runs unit tests on every PR and builds the ISO with QEMU smoke boots
(UEFI and BIOS) on `main`, on `v*` tags, and on PRs that change the image. See
[CI and builds](docs/ci.md).

## Use AGIOS

1. Boot the Live ISO. The website opens automatically.
2. Connect a model through ChatGPT sign-in or an API provider.
3. Describe your desktop, applications, and settings. The agent selects
   packages from Core/Extra and proposes a configuration, which the
   application validates.
4. Choose **Find room for the preview**. The application calculates the system
   size from package data and offers places to store the preview:
   - in RAM as a compressed zram image, without touching disks;
   - as a file on any drive with a filesystem (USB stick, another disk, or SD
     card), where rollback removes the file;
   - in a new partition in unallocated space, where rollback removes one
     partition entry;
   - by shrinking an NTFS/ext4 partition on the target disk, after a dry run
     and separate confirmation, with rollback restoring the boundary and
     growing the filesystem again;
   - by erasing a disk now, only when you explicitly choose that irreversible
     action.

   Enter the user password and, optionally, a LUKS2 encryption password here.
   Neither is sent to the agent.
5. Wait while the internal VM installs packages, clears its cache between
   batches, and boots the resulting system. Check the system in your browser.
6. If it is not right, choose **Put it back**. Otherwise shut down the preview
   system from inside it and choose **Install**. Select **Keep what’s on the
   disk** or **Erase the disk**, then confirm the target disk.
   - For a preview in a partition on the target disk, its nested partitions
     become disk partitions without copying their data.
   - For a preview in RAM or on another drive, files are copied into new
     partitions and checked against their checksums.

   The installer then rebuilds initramfs for the real hardware and registers
   the bootloader.
7. Remove the installation media and reboot. The installed system opens the
   first-boot check (`agi-os-verify`).

Storage options include ext4, Btrfs, XFS, and F2FS; GPT or MBR (msdos, BIOS
with GRUB); GRUB (BIOS/UEFI) or systemd-boot (UEFI); LUKS2 for the root
filesystem; and zram swap. Optional hibernation uses a swap file the size of
RAM inside the root filesystem, resumes through initramfs, and is checked by
`agi-os-verify --hibernate`. Hibernation is not available on F2FS.
On an MBR disk, installation alongside other systems uses a copy from a
preview in RAM or on another drive and needs two free primary partition
entries. The installer does not create logical partitions.

## Testing and development

```sh
python -B -m unittest discover -s tests -v
.local/venv/bin/python -B -m unittest discover -s web/tests -v
node --check web/static/app.js
./scripts/run-live-web-vm.sh [--firmware bios] [--memory 16384]   # external test VM
./scripts/run-live-web-vm.sh --mode disk                          # boot an installed disk
```

The shared installer engine is in
`archiso/airootfs/usr/local/share/agi-os/installer/`; the website, preview
storage, and finalization code are in `web/`. Test reports and screenshots are
kept out of Git and shared separately.

[Live, preview, and finalization](docs/local-web.md) ·
[Architecture](docs/installer-architecture.md) ·
[Testing an installed system](docs/installation-testing.md) ·
[Development model bridge](docs/development-bridge.md) ·
[CI and builds](docs/ci.md) ·
[Download and verification](docs/download.md)

## Licenses

The project is licensed under Apache-2.0 (`LICENSE`). The Archiso-based
profile retains GPL-3.0-or-later (`archiso/LICENSE`). Guacamole and the other
packages in the image retain their own licenses; the Guacamole LICENSE and
NOTICE files are included in the Live ISO.
