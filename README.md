# AGI OS

An Arch Linux live system with XFCE, Firefox, and Codex. The desktop, browser,
and agent terminal open automatically after boot. Connect to the network, sign
in to Codex **using the browser inside the live system**, and describe what you
want to install.

The agent inspects the hardware, works with you to choose the desktop,
filesystem, bootloader, and applications, then installs them using standard
Linux commands. XFCE provides the live environment; it does not determine the
desktop of the installed system. There is no custom installation engine,
installation plan format, or package repository. All packages in the image come
from the official Arch Core and Extra repositories.

## Try it in a virtual machine

The host needs `qemu-system-x86`, `qemu-ui-gtk`, and `qemu-img`:

```sh
./scripts/run-vm.sh
# Or specify another ISO:
./scripts/run-vm.sh /path/to/agi-os.iso
```

The script opens a QEMU window with 4 GB of RAM, 4 CPUs, NAT networking, and a
separate 64 GB virtual disk at `vm/agi-os-desktop.qcow2`. The disk image grows as
data is written and persists between runs. Host disks are not attached to the VM.
Release the mouse and keyboard with **Ctrl+Alt+G**.
Rebooting inside the VM switches booting to the virtual disk; starting the script
again boots the ISO.

## Sign in and install

1. Wait for automatic login to XFCE as the `agi` user.
2. Connect using the network icon on the panel. Ethernet uses DHCP.
3. Select **Sign in with ChatGPT** in the Codex terminal.
4. Sign in using Firefox inside the live system, then return to the terminal.
5. Describe the system you want. The agent performs the installation.

To reopen the agent, use Applications → System → Codex or run `codex`.
Run `codex login` to start authentication explicitly.
The browser and Codex run as the same user on the same machine, so the localhost
callback returns to the same Codex instance.

In the live session, `agi` can run `sudo` without a password to install the system.
The ISO contains no credentials. The session uses a temporary filesystem;
rebooting the live environment clears authentication and unsaved changes.
These live session settings are not a security template for the installed system.

## Build

On an up-to-date Arch Linux or compatible x86-64 system:

```sh
sudo pacman -S --needed archiso
sudo mkarchiso -v -w "$PWD/work/desktop" -o "$PWD/out" "$PWD/archiso"
```

Building requires internet access, root privileges for mount/chroot operations,
and space for packages, the working directory, and the ISO.
Output: `out/agi-os-desktop-<date>-x86_64.iso`.
When rebuilding after changes, use a new, empty working directory with `-w`:
Archiso keeps markers for completed build stages.

`archiso/pacman.conf` enables only `core` and `extra`; the host's repository
configuration is not inherited. `openai-codex` is installed from Extra without
npm or the AUR. Package versions depend on the state of the Arch mirrors at
build time.

## Validation

The earlier terminal prototype was tested in QEMU/KVM for BIOS/UEFI boot, DHCP,
HTTPS, and Codex 0.153.4 startup. UEFI showed a `systemd-loop@…sr0.service` error:
`systemd-dissect` reported `No suitable partitions found` for the virtual CD-ROM.
This did not prevent booting.

The graphical ISO built on 2026-09-09 was tested in QEMU/KVM with BIOS boot:
automatic XFCE login, Firefox and Codex startup, and opening the OpenAI login
page in Firefox after selecting **Sign in with ChatGPT** in Codex. The image
is approximately 1.8 GB.

Authentication with a user account and a full installation through conversation
remain to be tested by the user. Secure Boot, PXE, and automatic recovery from
failed installations are not currently claimed as supported.

## Next steps

- Complete an installation through conversation and verify that the installed system boots.
- Add other agent CLIs based on testing results.
- Develop AGI Assistant for working with an agent after installation.

## Upstream projects

The profile is based on `releng` from Archiso 90-1. It uses standard Archiso
boot and pacman keyring mechanisms, LightDM for graphical login, and
NetworkManager for networking.

- [Archiso](https://github.com/archlinux/archiso).
- [EndeavourOS ISO](https://github.com/endeavouros-team/EndeavourOS-ISO).
- [CachyOS Live ISO](https://github.com/CachyOS/CachyOS-Live-ISO).
- [Codex in Arch Extra](https://archlinux.org/packages/extra/x86_64/openai-codex/).
- [Codex authentication](https://learn.chatgpt.com/docs/auth).

The project license is Apache-2.0; see `LICENSE`. The Archiso-derived profile
in `archiso/` retains GPL-3.0-or-later; see `archiso/LICENSE`.
Packages inside the ISO retain their own licenses.
