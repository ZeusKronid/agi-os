# AGI OS conversational installation flow

AGI OS Installer preserves eight stages of a conventional OS installation.
The application owns state, provider connection, confirmation, execution and
verification. The LLM guides the dialogue and proposes structured choices.

## Dialogue rules

- Respond in the user's language. Explain the current stage and progress plainly.
- Offer a few relevant suggestions with reasons, and always invite a custom option.
- Desktop/window-manager selection is open text backed by repository lookup, not
  an enum. Search available packages and check prerequisites for the user's hardware.
- Reuse supplied answers. A complete initial request can satisfy several stages,
  but their validation and destructive-operation confirmation still apply.
- Convert broad requirements into agreed, observable results. Resolve contradictions
  and explain unavailable choices. Never silently replace a requested environment.
- Revisions invalidate the prior proposal and its confirmation. During execution,
  stop and assess partial state before discussing a new installation attempt.
- API keys and account passwords belong in private connection/account controls,
  never in the dialogue, generated configuration, provider context, or reports.
- The LLM has no arbitrary shell or disk-write tool. A validated proposal is still
  only a proposal; the application alone starts its installation worker.

## 1. Start the live environment

Boot the ISO into XFCE. AGI OS Installer opens automatically. Connect to the network
and choose a provider. Use ChatGPT browser sign-in, a provider API key, or a local
model endpoint, then select the model. The app inventories firmware and disks;
network, authentication and repository failures remain visible prerequisites.

**Exit:** live environment and provider are usable. A local desktop preview is not
an installation-ready live boot. The disk worker refuses to run outside Archiso.

## 2. Understand the desired system

The user describes their tasks and preferences. Discuss environments or no desktop,
software, language, keyboard layouts, time zone, account and computer names. Offer
recommendations where needed. Search the official package catalog when determining
available environments and dependencies. Use the chosen environment's settings,
services and session, including a usable login and relevant Wayland configuration.

**Exit:** agreed requirements are concrete enough to implement and check. Custom
choices receive the same treatment as suggested ones.

## 3. Choose the destination and layout

Use the actual disk inventory. Identify disks by path, size, model and serial where
available, and inspect existing partitions. Ask what data must be preserved.
Distinguish the installation medium and busy disks from eligible destinations.

Current executable storage handlers: whole-disk GPT; a separate boot partition;
unencrypted ext4, Btrfs, XFS or F2FS root; GRUB on BIOS/UEFI or systemd-boot on UEFI.
Encryption, swap, preservation and dual boot require additional handlers. If such
features are requested, explain the implementation boundary and obtain agreement
to an alternative before offering a supported configuration. Do not omit them.
Desktop and application choices remain open regardless of these storage handlers.

**Exit:** destination and storage consequences are clear. No disk changes occur.

## 4. Review and authorize changes

Show the complete configuration, actual disk identity, data-deletion scope, layout,
software, services, locale/account settings, custom configuration files and
requirements. Let the user return to the dialogue and revise anything.

The user explicitly confirms erasure of the identified disk in the review dialog
and enters the new user's password privately. The application binds this review
to the configuration digest and disk fingerprint. The model's response, a chat
suggestion, silence or timeout cannot start disk writes. The worker rechecks the
configuration, disk identity, readiness and repository packages before partitioning.

**Exit:** unchanged configuration and matching target are authorized for execution.
A refusal leaves the disk unchanged.

## 5. Install the system

The worker creates the agreed partitions and filesystems, mounts the target, and
installs the base OS and requested packages from official repositories. Show the
current operation and keep the UI responsive. The user can request cancellation.

On failure or cancellation, report partial state and clean up the worker's mounts.
Do not claim success, silently omit packages or automatically retry by wiping the
disk again. A failed attempt remains a failed attempt even after manual recovery.

**Exit:** the agreed software is installed on the target without unresolved errors.
This is not proof that it boots.

## 6. Configure boot and access

Configure mounts, bootloader/initramfs, ordinary account, password-protected sudo,
locked root password, locale, keyboard, time zone, hostname, network, services,
chosen graphical session and agreed environment files. The live user's empty
password, autologin and passwordless sudo are not copied to the target.

Verify the installed packages, session file where applicable, enabled display
manager, mount configuration and boot operations. Write a non-secret installation
record and install the offline acceptance tool. Provider credentials and live
browser profiles are not copied. Sync and unmount before declaring the disk ready.

**Exit:** configuration checks pass; status is first boot pending, not complete.

## 7. Boot from the installed disk

Explain the next steps and offer shutdown after all operations and cleanup finish.
Remove/disconnect the installation medium. Start from the installed disk. In a VM,
start a new QEMU process in disk mode with the same disk and UEFI variables.

Run `agi-os-verify --gui`, or `agi-os-verify` in a console. Desktop environments
supporting XDG autostart start the GUI checker automatically; other compositors
may require manual launch. LLM authentication is not required for verification.

**Exit:** independent boot from the recorded installed root and user login have
been observed. Booting the live desktop or succeeding inside chroot does not count.

## 8. First use and acceptance

The acceptance tool checks root identity/filesystem, account, installed packages,
locale, time zone, hostname, selected session, service enablement and networking.
The user tests their actual applications, keyboard layouts and agreed workflows,
then explicitly confirms those requirements. The tool creates a persistence marker
and requires a different boot ID with that marker intact after a second boot.

**Exit:** automatic checks, user requirement checks and persistence pass. Otherwise
acceptance remains pending/failed. The offline report is saved in the installed
user's local state directory. This checker is not a continuing LLM assistant.
