# AGI OS

An Arch Linux live system that opens **AGI OS Installer**, our own application,
after boot. Choose an LLM provider, connect your account or API, and describe the
system you want. The application preserves the eight installation stages while
using a conversation for preferences and decisions.

## Installation flow

1. Boot the live environment and connect a provider.
2. Describe your requirements; choose suggestions or propose your own options.
3. Agree on the destination disk and storage layout.
4. Review the complete configuration and explicitly authorize disk changes.
5. Install the base system and selected packages.
6. Configure boot, accounts, networking, and the requested environment.
7. Shut down, disconnect the ISO, and boot from the installed disk.
8. Verify first use, the agreed requirements, and persistence across another boot.

The [flow specification](archiso/airootfs/usr/local/share/agi-os/installation-flow.md)
and [acceptance tests](docs/installation-testing.md) describe each stage.

Desktop and window-manager choices are open: there is no KDE/GNOME/XFCE enum or
fixed installation profile. The assistant searches the official Core and Extra
package catalog and proposes packages, services, sessions, and configuration files.
It can help with Hyprland, Sway, i3, Cinnamon, MATE, LXQt, other available
environments, or a system without graphics. Package availability is checked;
compatibility and a working final configuration still require acceptance testing.
XFCE is only the live desktop.

## Connect a provider

- **ChatGPT account:** sign in through the browser inside the live system. The
  application uses the [official Codex app-server](https://learn.chatgpt.com/docs/app-server)
  as an isolated conversation backend. It does not open the Codex terminal UI.
- **OpenAI API:** API key and selectable model, using the
  [Responses API with structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
- **Anthropic / Claude API:** API key and selectable model, using
  [Messages and tool responses](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview).
- **Google Gemini API:** API key through its
  [OpenAI-compatible API](https://ai.google.dev/gemini-api/docs/openai).
- **Ollama:** local model with
  [structured outputs](https://docs.ollama.com/capabilities/structured-outputs).
- **Other OpenAI-compatible APIs:** custom endpoint, optional API key, and model.
  The service must support chat completions with JSON-schema structured outputs.

The application loads available models and also accepts a model identifier typed
by the user. Account/model availability depends on the provider. Claude and Gemini
connections currently use API keys; their consumer subscription login is not
implemented. API usage can be billed separately from chat subscriptions.

API keys stay in application memory and are not added to model messages or reports.
The ChatGPT backend runs in bubblewrap with an ephemeral home and private /dev;
it cannot access host disks or import an existing Codex home. Closing it discards
its local login state. Passwords for the installed user are entered in a private
confirmation dialog and passed to the local worker over stdin, never to the LLM.
No provider credentials are copied to the installed system.

## What executes an installation

The LLM proposes structured choices. The native Python/GTK application validates
those choices, checks packages, shows the actual disk identity and complete review,
and starts a separate privileged worker only after confirmation. A new proposal
invalidates the old review. The model has no disk-writing or arbitrary shell tool.

The worker rechecks disk identity and rejects busy/read-only disks. It runs only
inside a booted Archiso live environment, uses ordinary Linux installation tools,
and reports failures and cancellation without claiming success. The live `agi`
user currently has passwordless sudo; that live policy is not installed on the
new system. The target gets a normal user with password-protected sudo and a locked
root password.

Current storage handlers implement **whole-disk GPT installation**, an unencrypted
root filesystem (ext4, Btrfs, XFS, or F2FS), a separate boot partition, and GRUB
(BIOS/UEFI) or systemd-boot (UEFI). There is currently no encryption, swap,
partition-preservation, or dual-boot handler. Such requests must be explained and
renegotiated before a supported proposal is offered; the app must not silently
omit requirements. These implementation boundaries are separate from the open
choice of environments and applications.

After installation, `agi-os-verify --gui` or `agi-os-verify` checks the installed
root, account, packages, settings, services, and persistence. The GUI is registered
with XDG autostart and the applications menu; compositors without XDG autostart
need manual launch. The user confirms their actual application workflows; a
second boot is required before full acceptance. There is no automatic LLM
continuation after reboot.

## Try the interface locally

On Arch-compatible hosts, the interface needs `python-gobject` and `gtk3`:

```sh
./scripts/run-installer.sh --demo
```

Demo mode uses fake responses and a fake disk and never connects to an LLM or
writes disks. Its screens and simulated installation are explicitly labelled.
Without `--demo`, provider conversations work, but the disk worker refuses to run
outside the live environment.

## Build the ISO

On an up-to-date Arch-compatible x86-64 system:

```sh
sudo pacman -S --needed archiso
sudo mkarchiso -v -w "$PWD/work/installer-build" -o "$PWD/out" "$PWD/archiso"
```

Use a new, empty work directory for each build. Archiso keeps completed-stage
markers. Building needs internet, root for mount/chroot operations, and disk space.
The profile enables only official `core` and `extra` repositories. Output:
`out/agi-os-desktop-<date>-x86_64.iso`. Existing images from 2026-09-09 predate this
application and cannot test it.

## Test in QEMU/KVM

The host needs `qemu-system-x86`, `qemu-ui-gtk`, `qemu-img`, and `edk2-ovmf`.
For `--gl`, also install `qemu-hw-display-virtio-vga-gl`. Ordinary boot checks use
standard VGA so the base QEMU packages are sufficient.

```sh
# New scenario: UEFI, 4 CPUs, 6 GiB RAM, 64 GiB virtual disk, NAT.
./scripts/run-vm.sh --name first-install
# Once installation has shut down, boot the same disk without any ISO:
./scripts/run-vm.sh --name first-install --mode disk
# Independent BIOS scenario:
./scripts/run-vm.sh --name bios-install --firmware bios
# Optional accelerated VirtIO graphics for compositors that need it:
./scripts/run-vm.sh --name compositor-install --gl
```

Use `--iso /path/to/image.iso` for an exact artifact. Otherwise install mode selects
the newest desktop ISO by filename. Each scenario has its own disk and persistent
UEFI variables under `vm/<name>/`. Existing disks are never overwritten; use a new
name for a fresh scenario. Host disks/directories are not attached. `--headless`
is available for automated boot checks; a local QMP socket is placed in the scenario
directory. Release captured input with **Ctrl+Alt+G**.

For Ollama on the QEMU host, use `http://10.0.2.2:11434` and configure the host's
Ollama listener to accept that connection. Inside the VM, `localhost` means the VM.

## Development checks and validation status

```sh
python -B -m unittest discover -s tests -v
GDK_BACKEND=x11 python -B tests/gui_smoke.py
```

Unit checks exercise open environment choices, input validation, consent
invalidation, provider response adapters, host-write refusal, installation ordering,
and failure handling with a fake executor. The GTK smoke test uses the demo
backend. These checks do not establish a successful real installation or paid
provider conversation. See the acceptance guide for recording real results.

The new native application was boot-tested in QEMU/KVM with UEFI, and the
ChatGPT login page was reached inside the VM. The unit and GTK checks pass.
See the [validation record](docs/test-results/2026-09-10-installer-smoke.md).
Full provider-login and installation acceptance remain pending. Secure Boot, physical GPU/Wi-Fi support, and unattended recovery are not
claimed as tested.

## Upstream and license

The live profile derives from [Archiso](https://github.com/archlinux/archiso)
releng 90-1. It uses LightDM, XFCE and NetworkManager. `openai-codex` comes from
Arch Extra and is retained for the ChatGPT backend and optional diagnostics.

The project is Apache-2.0 (`LICENSE`). The Archiso-derived profile in `archiso/`
retains GPL-3.0-or-later (`archiso/LICENSE`). Packages in the ISO retain their licenses.
