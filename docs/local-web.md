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
   Configuration files proposed by the model are limited: `system_files` may not
   touch accounts, privileges, storage, boot, the package manager or anything
   that runs as root or inside every process (`ld.so.*`, `profile.d`, systemd
   system/user units and generators, cron, `tmpfiles.d`, `etc/xdg/autostart`,
   udev `RUN`, modprobe `install`, LightDM scripts, `LD_PRELOAD`-style
   environment). Whatever runs at login — `~/.config/autostart`,
   `~/.config/systemd/user`, `exec` lines of compositor/WM configs, the greetd
   command — is listed in a separate review block with the exact lines and needs
   its own confirmation before the preview is built.
   A user who does not want to choose («Выберите за меня») gets the AGIOS
   standard system (`domain.DEFAULT_SYSTEM`: XFCE with LightDM, Firefox,
   NetworkManager and volume applets, ext4, systemd-boot on UEFI or GRUB on
   BIOS); the agent then asks only for personal settings — user name, language,
   layouts, time zone and the disk.
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
   *Secure Boot* (UEFI with systemd-boot, a checkbox before the size
   calculation): `sbctl` creates the system's own keys right after the base
   system, signs `systemd-bootx64.efi` into the `.signed` copy that `bootctl`
   installs and the kernel, and `sbctl verify` must report no unsigned file.
   sbctl's pacman and mkinitcpio hooks re-sign them on every update.
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
   acceptance ID is written for `agi-os-verify`. For a signed system the user may
   also enroll its keys: only when the firmware is in Setup Mode (checked before
   any disk change), with `sbctl enroll-keys --microsoft` so Microsoft-signed
   option ROMs and Windows keep booting. Otherwise the page explains how to
   enroll later. `agi-os-verify` checks the signatures and, after enrollment,
   that Secure Boot is on.

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
`--firmware uefi-sb` uses the Secure Boot OVMF build (SMM) with an empty
variable store, i.e. Setup Mode; enrolled keys persist in
`.local/live-test/OVMF_VARS-uefi-sb.fd`, so `--mode disk --firmware uefi-sb`
then boots with Secure Boot enforced.
`AGIOS_TEST_HARDWARE=laptop` adds a Notebook SMBIOS chassis and an Intel HD Audio
controller (they drive the driver plan and the "preview cannot verify" list) and
swaps the NIC for an Intel e1000e so the inventory names a real card. Only that serial is an
eligible target in the marked test VM. The VNC console is `127.0.0.1:5997`;
`scripts/web/qa-driver.py` drives the site API, QMP screenshots and input.
The LLM comes from the private host bridge; production boots ask the user to
connect a provider.

## Live runtime

- `agi-web.service`: website/controller at `127.0.0.1:8787` (system user
  `agi-web`, groups `kvm render video disk optical systemd-journal`, state in
  `/var/lib/agi-os` with mode 0700). Root helpers via `sudo -n`: `storage_worker.py`
  (probe/prepare/revert), `finalize_worker.py`.
- `agi-guacd.service`: Guacamole gateway at `127.0.0.1:14822` (user `agi-web`).
- `agi-guest.service`: the installer inside the inner VM only.
- `agi-qa.service`: test instrumentation, active only with the fw_cfg marker
  (runs as root there; it never starts on real hardware).
- ChatGPT sign-in: `openai-codex` is present only as the provider backend. The
  site starts `codex app-server` inside bubblewrap with an ephemeral home, no
  shell tool and a read-only sandbox. The Live image ships no Codex terminal
  entry, Codex configuration or agent instructions for a terminal session.

Privileges in Live (`etc/sudoers.d/10-agi-live`): only `agi-web` may use sudo,
and only for the exact command lines the site runs — the two root helpers,
`pacman -Sy --noconfirm` (package catalog), `shutdown -h|-r +1` and, on test
stands, reading the fw_cfg mirror value. The desktop user `agi` (browser,
terminal) has no sudo, no `wheel` membership and no disk group; the ChatGPT
sign-in adapter runs under `agi-web` inside bubblewrap. All passwords (`root`, `agi`, `agi-web`) are locked; LightDM
autologin of `agi` is the only login, there is no root autologin on a console.
Because the site has no desktop session, the ChatGPT sign-in page is opened by
the site's own browser tab (`login_url` in `/api/state`), not by `xdg-open`.

What this does not cover (see the root helpers' threat model): the site's API
on `127.0.0.1:8787` is local-only, not per-user, so any process of `agi` can
drive the site — including the consented disk operations — and read
`login_url`; `agi-web` holds the `disk` group, which QEMU needs for a partition
preview and which is close to root. With every password locked there is no
rescue login on a text console of Live; debugging is done on test stands
(`agi-qa.service`).

Session state lives in `/var/lib/agi-os`, which is in RAM in the Live
environment. After a Live restart an in-memory preview is gone (nothing was on
disk); file and partition previews are kept and found again:

- Every file or partition preview carries a secret-free *preview record*: the
  agreed configuration, the identity of the target disk, the storage kind, the
  status (`installing`, `ready`, `failed`, `finalizing`) and a short journal of
  the operations. A file preview keeps it in `AGIOS-PREVIEW/preview.json` next to
  `preview.qcow2`; a partition preview keeps it in the unused gap of its nested
  GPT (sectors 64–2047 of the preview partition, before the first nested
  partition), outside every filesystem and outside LUKS, so it is readable
  without the encryption passphrase.
- At start the site scans the computer's media (read-only mounts without journal
  replay) for `AGIOS-PREVIEW` partitions and `AGIOS-PREVIEW/preview.qcow2` files.
  A completely installed preview can be *continued*: it is reattached, bound to
  the same target disk (found by size, model, serial and WWN even under another
  device name) and can be started or installed. An unfinished installation is
  never shown as a success: *retry* removes its storage and returns its
  configuration to the size-and-place step. Any found preview can be *removed*.
- A record read from a medium is untrusted: it is validated completely, a preview
  file with a backing or external data file is refused, and the undo of the
  storage (including the boundary of a shrunk partition) is derived from the
  current partition layout, not taken from the record.
- Promotion zeroes the nested table and the record; copy and undo remove the
  storage together with its record.

## Logs and diagnostics

Every component writes structured records to journald (`installer/journal.py`,
native journal protocol, no extra packages):

| Identifier | Process |
| --- | --- |
| `agios-web` | the website: API calls, preview build and finalization steps, helper calls |
| `agios-storage` | `storage_worker.py` (root): operations and every command it runs |
| `agios-finalize` | `finalize_worker.py` (root) |
| `agios-worker`, `agios-guest` | the installer inside the inner VM |

Fields: `AGIOS_EVENT` (machine-readable name such as `build.failed`),
`AGIOS_OPERATION` (one id per preview build or finalization, passed to the
root helpers as `trace` in their JSON request, so one operation can be followed
across processes), `AGIOS_DATA` (JSON details), `AGIOS_ERROR` (exception type;
the traceback is part of `MESSAGE`). Every record passes `journal.redact()`:
secret-named keys (`password`, `passphrase`, `*_token`, `api_key`, …), API key and
token formats, crypt hashes and URL credentials become `***`. Commands that get a
secret on stdin never have their output logged.

```sh
journalctl -b -t agios-web -t agios-storage -t agios-finalize
journalctl -b AGIOS_OPERATION=build-…      # one preview build across processes
```

The inner VM's journal lives in its memory; it is forwarded to the serial
console (`systemd.journald.forward_to_console=1`) and ends up in
`/var/lib/agi-os/vm/<VM>/guest-console.log` on the Live side.

**Diagnostics** button (page header, `POST /api/diagnostics`): a
`agios-diagnostics-<time>.tar.gz` with the AGIOS journal of this boot, the
journal of Live services, warnings and errors of the whole system, the site state
and session record, the hardware inventory (disk serial numbers shortened to the
last four characters), versions (ISO, source revision, kernel, key packages) and
the tails of the preview VM logs — all through the same redaction. The site
reads the system journal through the `systemd-journal` group, without sudo.
Nothing is sent anywhere automatically; the user saves the archive and decides.

## Logs and secrets

The user's password and the disk-encryption passphrase travel only in memory
and over stdin/virtio (site → preview VM installer → `chpasswd`/`cryptsetup`;
site → `finalize_worker.py`); API keys stay in the provider object. None of
them is written to `session.json`, events, the API state or the installed
system's `installation.json`, and a failing command that was fed a secret on
stdin never echoes its output (tests: `SecretAuditTests`,
`test_no_secret_in_events_commands_or_installed_files`).

What Live keeps, all in RAM (lost at power-off):

- `/var/lib/agi-os/session.json`: the conversation, configuration and preview
  state — no secrets, but whatever the user typed into the chat.
- `/var/lib/agi-os/vm/web-*/`: `qemu.log`, `guest-console.log` (the installer
  VM's serial console, truncated by QEMU on every installer start), UEFI
  variables and sockets of each preview VM. Kept while the preview exists and
  after any failure (diagnostics); a new preview VM keeps only the newest
  earlier directory; all are removed after a successful finalization.
- The journal (`Storage=volatile`), bounded to 128 MiB (`agi-os-size.conf`).

## Updates of the installed system

The installer adds `agi-os-update` to every installed system:

- `agi-os-update-check.timer` (daily, 10 min after boot, persistent) runs
  `agi-os-update check` as root. It refreshes a private copy of the sync
  databases in `/var/lib/agi-os/update-db`, never the system's own, so a later
  `pacman -S` cannot become a partial upgrade. The result goes to
  `/var/lib/agi-os/update-status.json`; interactive shells print a one-line
  reminder from `/var/lib/agi-os/update-notice`.
- `sudo agi-os-update apply` refuses on a discharging battery below 30 %
  (`--force` overrides), with less than 2 GiB free, or while pacman is busy.
  On a btrfs root it first takes a read-only snapshot
  `/.snapshots/pre-update-*` (the three newest are kept). Then it updates
  `archlinux-keyring`, runs `pacman -Su`, refreshes the bootloader when its
  package changed (`bootctl update`; GRUB is reinstalled exactly as the
  finalization did) and reports `.pacnew` files and whether a reboot is needed.
  `systemd-boot-update.service` is enabled for systemd-boot as well.
- Desktops get "AGI OS — Updates" in the menu and a reminder window at login,
  at most once a day while updates wait: the list and one button. The password
  goes only to `sudo -S` on stdin.
- `agi-os-verify` checks that the timer is enabled.

Not yet: discussing updates with the agent in the installed system (it has no
provider), a bootable rollback (the snapshot is a file-level copy; the root is
the top-level btrfs volume), automatic `.pacnew` merging, AUR packages.

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
  comes back from the image: the kernel must not report a rollback and the session
  must have been stopped for longer than a real power-off and resume take. With
  hibernation chosen, acceptance is complete only after that test. In a virtual
  machine the system hibernates with `HibernateMode=shutdown`
  (`/etc/systemd/sleep.conf.d/agi-os-hibernate.conf`): QEMU handles ACPI S4 as a
  delayed power-off, so in platform mode the guest kernel sees the sleep call
  return, rolls the hibernation back and erases the image. Real firmware keeps
  platform mode, so the trial is not run inside the preview VM: hibernation is
  checked on the installed computer. An unreadable kernel log is not a pass.
- Secure Boot: the Live ISO itself is not signed and boots only with Secure Boot
  off or in Setup Mode. Booting it with Secure Boot on would need Arch's
  unsigned kernel behind a Microsoft-signed `shim` plus a MOK the user enrolls
  by hand in MokManager at the first boot; the kernel, systemd-boot and
  initramfs of the ISO would have to be signed with that MOK at build time.
  That is a separate, human decision about key custody (like ISO signing).
  GRUB installs are not signed; Secure Boot is offered with systemd-boot only.
  Enrolling own keys may make BitLocker ask for its recovery key once.
- Physical hardware runs are still pending; QEMU/KVM (nested for the inner VM)
  is the verified environment.
