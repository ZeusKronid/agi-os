# AGIOS Live website, reversible preview and installation

AGIOS is one bootable Live ISO. Inside the Live environment Firefox opens
`http://localhost:8787`. The conversation controller, provider adapter,
Guacamole and QEMU all run there. Nothing is written to the computer's disks
until the user explicitly confirms a specific, described change.

## Flow

1. **Conversation.** The agent proposes a configuration; the app validates it
   against the package catalog and the real disk inventory. The page shows the
   computer's hardware (CPU, chassis, GPU, network, sound, Bluetooth, TPM,
   Secure Boot), the driver packages the engine will add for it and what the
   preview on virtual devices cannot verify; the model receives the same data.
2. **Size and place.** The app computes the exact installed size from package
   metadata (`pacman -Sp`/`-Si`, including dependencies) and lists where the
   preview can live, each option with its undo:
   - *memory*: a zstd zram device holding the preview image — disks untouched;
   - *file* on any other medium with a filesystem (USB stick, second disk, SD
     card; exFAT/NTFS/ext4/…) — undo deletes one file;
   - *partition* in unpartitioned space of any GPT disk — undo deletes one
     partition entry; on the target disk this later becomes the system without
     copying;
   - *shrink* an NTFS/ext4 partition of the target disk (dry run first, separate
     typed confirmation) — undo restores the boundary and grows the filesystem;
   - *erase* the target disk now — explicit, typed, not reversible.
   Non-destructive options that fit are recommended first; memory needs
   `MemAvailable − VM RAM − 3 GiB ≥ size / 1.3` and is monitored during the
   installation so it stops cleanly instead of failing mid-way.
3. **Preview.** The inner VM boots the same Live medium headless
   (`agios.guest` on the kernel command line, `agi-guest.service`) and installs
   into the preview storage in batches, dropping the package cache between
   batches (`fstrim` + `discard=unmap` keep an in-memory image small). Then it
   restarts from the installed image; Guacamole shows it in the browser.
   LUKS2 root encryption and zram swap are configured here when chosen.
4. **Decision.** *Not right* → "return everything as it was" undoes the storage.
   *Install* → the user chooses *alongside existing systems* or *erase the
   disk*, types the disk path and confirms:
   - preview partition on the target disk → *promote*: its nested partitions
     become real GPT entries at the same sectors (no data moves);
   - anything else → *copy*: fresh partitions, `rsync -aHAX`, then a checksum
     comparison pass; UUIDs in fstab/boot entries are regenerated.
   Finally missing hardware drivers are completed for the real computer (a
   failure is reported, never hidden), the initramfs is rebuilt, the boot loader is
   registered in firmware (BIOS GRUB or UEFI systemd-boot/GRUB) and a new
   acceptance ID is written for `agi-os-verify`.

## Build

```sh
sudo ./scripts/build-iso.sh        # or --prepare-only, then run mkarchiso as root
```

Everything comes from the official `core`/`extra` repositories through
`archiso/pacman.conf` (signatures required). The script adds the website, the
Guacamole 1.6.0 browser client built from the official source release, and the
guacd runtime as a squashfs made from the pinned `guacamole/guacd:1.6.0` image
(`agi-guacd.service` runs it with `RootImage=`). No host package cache, no CPU
specific packages and no second installer ISO are involved.

## Test locally

```sh
AGIOS_TEST_MIRROR=https://geo.mirror.pkgbuild.com ./scripts/run-live-web-vm.sh [--firmware bios] [--memory 16384]
./scripts/run-live-web-vm.sh --mode disk        # boot the installed target disk without the ISO
```

The outer VM is the "computer": it boots the ISO from an optical drive with a
blank 20 GiB target disk (serial `AGIOS_TARGET`) and, when
`.local/live-test-media.img` exists, an exFAT USB stick.
`AGIOS_TEST_HARDWARE=laptop` adds a Notebook SMBIOS chassis and an Intel HD Audio
controller (they drive the driver plan and the "preview cannot verify" list) and
swaps the NIC for an Intel e1000e so the inventory names a real card. Only that serial is an
eligible target in the marked test VM. The VNC console is `127.0.0.1:5997`;
`scripts/web/qa-driver.py` drives the site API, QMP screenshots and input.
The LLM comes from the private host bridge; production boots ask the user to
connect a provider.

## Live runtime

- `agi-web.service`: website/controller at `127.0.0.1:8787` (user `agi`, groups
  `kvm disk optical`). Root helpers via `sudo -n`: `storage_worker.py`
  (probe/prepare/revert), `finalize_worker.py`.
- `agi-guacd.service`: Guacamole gateway at `127.0.0.1:14822`.
- `agi-guest.service`: the installer inside the inner VM only.
- `agi-qa.service`: test instrumentation, active only with the fw_cfg marker.

Session state lives in `/var/lib/agi-os`. After a Live restart an in-memory
preview is gone (nothing was on disk); file/partition previews are kept.

## Limits

- Disks with MBR partition tables: only the explicit whole-disk erase.
- Shrinking: NTFS and ext4 only; NTFS marked dirty (Windows fast startup or
  hibernation) is refused by `ntfsresize` — shut Windows down fully first.
- Swap is zram by default. `swap: "hibernate"` adds a swap file `/swap/swapfile`
  as large as the real computer's RAM inside the root (inside LUKS when encrypted;
  a separate subvolume on Btrfs), `resume=UUID=… resume_offset=…` and the
  `resume` initramfs hook. The file is reserved with `fallocate`/`mkswapfile`, so an
  in-memory preview does not grow by the RAM size; promotion keeps it in place,
  a file-by-file copy recreates it on the target with the new UUID and offset.
  F2FS is refused for hibernation. `agi-os-verify` checks the swap file,
  `/sys/power/resume*` and logind `CanHibernate`; `agi-os-verify --hibernate`
  (or the button in the GUI) hibernates once and passes only if the same session
  comes back; with hibernation chosen, acceptance is complete only after that test.
- Physical hardware runs are still pending; QEMU/KVM (nested for the inner VM)
  is the verified environment.
