"""Privileged installation worker. Only runs inside an Archiso live boot.

Input: one validated configuration/consent/password record on stdin (with an
optional private LUKS passphrase), followed optionally by {"cancel": true}.
Output: secret-free JSONL progress events. No shell code or provider
credentials are accepted by this process.
"""

import fcntl
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from configcheck import HINTS, tool_checks
from domain import (GIB, SWAPFILE, Configuration, ValidationError, console_font_exists, console_keymap_exists,
                    hibernation_swap_size, system_path_allowed)
from hardware import driver_plan, initramfs_config, profile, virtual
from journal import Logger
import layout
from layout import CRYPT_NAME, partition_path
from system import Catalog, inventory, live_environment, selected_disk
import update


TARGET = Path("/mnt/agi-os")
HERE = Path(__file__).resolve().parent
BASE_PACKAGES = ("base", "linux", "linux-firmware", "networkmanager", "sudo", "python", "zram-generator")
LOG = Logger("worker")


def emit(kind, **data):
    print(json.dumps({"kind": kind, **data}, ensure_ascii=False), flush=True)


class Cancelled(RuntimeError):
    pass


class Runner:
    def __init__(self, log=None):
        self.cancel = threading.Event()
        self.log = log or LOG

    def run(self, args, input_text=None, timeout=1800, progress=None):
        """Run a command; progress, if given, receives its output while it runs."""
        if self.cancel.is_set():
            raise Cancelled("Installation stopped. The disk may be partly changed.")
        started = time.monotonic()
        try:
            output = self._stream(args, timeout, progress) if progress else self._run(args, input_text, timeout)
        except Exception as exc:
            # Output of a command that received a secret on stdin is never logged.
            self.log.warning("command.failed", f"{args[0]}: {exc}" if input_text is None else f"{args[0]}: failed",
                             args=list(args), seconds=round(time.monotonic() - started, 2))
            raise
        self.log.info("command.done", args[0], args=list(args), seconds=round(time.monotonic() - started, 2))
        return output

    def _stream(self, args, timeout, output):
        """Like _run without input, handing the output to output() as it arrives."""
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        started, tail = time.monotonic(), ""
        with proc.stdout:
            while True:
                if self.cancel.is_set() or time.monotonic() - started > timeout:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                    if self.cancel.is_set():
                        raise Cancelled("Installation stopped. A partial installation is left on the disk.")
                    raise ValidationError(f"Timed out: {args[0]}")
                ready, _, _ = select.select([proc.stdout], [], [], 1)
                if not ready:
                    continue
                chunk = os.read(proc.stdout.fileno(), 65536)
                if not chunk:
                    break
                text = chunk.decode(errors="replace")
                tail = (tail + text)[-2500:]
                output(text)
        if proc.wait():
            raise ValidationError(f"{args[0]} failed (code {proc.returncode})\n{tail}")
        return tail

    def _run(self, args, input_text, timeout):
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, start_new_session=True,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        started = time.monotonic()
        # communicate drains output while waiting; the secret, if any, is only sent on stdin.
        first = True
        while True:
            try:
                output, _ = proc.communicate(input=input_text if first else None, timeout=1)
                break
            except subprocess.TimeoutExpired:
                first = False
                if self.cancel.is_set() or time.monotonic() - started > timeout:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.communicate()
                    if self.cancel.is_set():
                        raise Cancelled("Installation stopped. A partial installation is left on the disk.")
                    raise ValidationError(f"Timed out: {args[0]}")
        if proc.returncode:
            # Never echo input to a credential operation, even if a subprocess does so.
            detail = "" if input_text is not None else output[-2500:]
            raise ValidationError(f"{args[0]} failed (code {proc.returncode})\n{detail}")
        return output


SBCTL_EFI = "/usr/lib/systemd/boot/efi/systemd-bootx64.efi"


def packages_for(config, hardware, secure_boot=False):
    """Everything the target receives: base, filesystem tools, the user's choices and
    the drivers derived from the real computer's hardware (never from the preview VM).
    Secure Boot adds sbctl: own keys, signing and re-signing on every kernel update."""
    packages = [*BASE_PACKAGES, config.filesystem + "-progs" if config.filesystem == "btrfs"
                else {"ext4": "e2fsprogs", "xfs": "xfsprogs", "f2fs": "f2fs-tools"}[config.filesystem],
                *config.packages, *config.effective_fonts(),
                *driver_plan(hardware, config.packages, config.session)["packages"]]
    if config.bootloader == "grub":
        packages += ["grub", "efibootmgr"]
    if config.session:
        packages += ["python-gobject", "gtk3"]
    if secure_boot:
        packages.append("sbctl")
    if config.lvm:
        packages.append("lvm2")  # its mkinitcpio hook activates the root volume group
    return list(dict.fromkeys(packages))


BATCH = 12


def retrying(runner, args, attempts=3, **kw):
    """Package downloads fail on flaky mirrors; a retry is cheap and pacman resumes what it has."""
    for attempt in range(1, attempts + 1):
        try:
            return runner.run(args, **kw)
        except ValidationError as exc:
            if attempt == attempts or "pacman" not in str(exc) and "pacstrap" not in str(exc):
                raise
            emit("progress", stage=5, text=f"Retrying the package download (attempt {attempt + 1} of {attempts})…")
            time.sleep(10 * attempt)


def trim_cache(runner):
    # Package archives never compress further; keeping them would double an in-memory preview.
    runner.run(["arch-chroot", str(TARGET), "pacman", "-Scc", "--noconfirm"])
    try:
        runner.run(["fstrim", str(TARGET)], timeout=300)
    except ValidationError:
        pass  # Media without discard support simply keep their blocks allocated.


def resolved(relative):
    """Where `relative` really lands inside the target after symlinks, as a relative path."""
    real = (TARGET / relative).resolve()
    if not real.is_relative_to(TARGET.resolve()):
        raise ValidationError("A settings file points outside the installed system")
    return real.relative_to(TARGET.resolve()).as_posix()


def sbctl_unsigned(output):
    """Files `sbctl verify` reports as not signed (it marks them with ✗). Windows Boot
    Manager on a shared ESP (CMP-151) is signed by Microsoft, not by this system's keys;
    enrolling with --microsoft keeps it bootable, so it is not ours to sign."""
    files = [line.split("✗", 1)[1].split(" is not signed")[0].strip()
             for line in output.splitlines() if "✗" in line]
    return [f for f in files if "/efi/microsoft/" not in f.lower()]


PAGE = 4096  # resume_offset counts pages; x86_64 pages are 4 KiB.


def first_extent_offset(filefrag):
    """resume_offset from `filefrag -v`: the first extent's physical start, in pages."""
    block = re.search(r"blocks? of (\d+) bytes", filefrag)
    first = re.search(r"^\s*0:\s*\d+\.\.\s*\d+:\s*(\d+)\.\.", filefrag, re.MULTILINE)
    if not block or not first:
        raise ValidationError("Could not find where the swap file is on the disk (resume_offset)")
    return int(first.group(1)) * int(block.group(1)) // PAGE


HIBERNATE_MODE_FILE = "etc/systemd/sleep.conf.d/agi-os-hibernate.conf"


def hibernate_mode(hardware):
    """How the computer powers off after writing the hibernation image. QEMU/KVM treat
    ACPI S4 as an asynchronous power-off request: the guest kernel sees the sleep call
    return, takes it for a wake-up, rolls the hibernation back and erases the image
    signature before the VM stops ("PM: Image not found" at the next boot). A virtual
    machine therefore hibernates in shutdown mode; real firmware keeps platform mode."""
    return "shutdown" if virtual(hardware) else "platform"


def create_swapfile(runner, root, filesystem, size):
    """Swap file for hibernation inside a mounted root; returns its resume_offset.

    Space is reserved without writing data (fallocate; mkswapfile on btrfs), so an
    in-memory preview does not grow by the size of RAM. On btrfs the file lives in
    its own subvolume (kept out of root snapshots) and is created NOCOW by mkswapfile.
    """
    path = Path(root) / SWAPFILE
    if filesystem == "btrfs":
        # With the subvolume layout (CMP-153) @swap is already mounted there; a flat root
        # gets a nested subvolume, which root snapshots leave out just the same.
        if not path.parent.is_dir():
            runner.run(["btrfs", "subvolume", "create", str(path.parent)])
        runner.run(["chmod", "700", str(path.parent)])
        runner.run(["btrfs", "filesystem", "mkswapfile", "--size", f"{size // GIB}g", str(path)])
        output = runner.run(["btrfs", "inspect-internal", "map-swapfile", "-r", str(path)]).strip()
        if not output.isdigit():
            raise ValidationError("Could not find where the swap file is on btrfs (resume_offset)")
        return int(output)
    runner.run(["mkdir", "-m", "700", "-p", str(path.parent)])
    runner.run(["fallocate", "-l", str(size), str(path)])
    runner.run(["chmod", "600", str(path)])
    runner.run(["mkswap", str(path)])
    return first_extent_offset(runner.run(["filefrag", "-v", str(path)]))


def swap_fstab_line():
    # Lower priority than zram (100): the file is used when zram is full and for hibernation.
    return f"/{SWAPFILE} none swap defaults,pri=10 0 0\n"


def resume_parameter(filesystem_uuid, offset):
    return f"resume=UUID={filesystem_uuid} resume_offset={offset}"


def boot_options(root_uuid, luks_uuid=None, resume=None, flags=(), lvm=False):
    """Kernel options of the systemd-boot entries; flags such as rootflags=subvol=@. On LVM
    the root is a logical volume inside the opened LUKS container, found by its file system UUID."""
    unlock = [f"cryptdevice=UUID={luks_uuid}:{CRYPT_NAME}"] if luks_uuid else []
    root = [*unlock, f"root=/dev/mapper/{CRYPT_NAME}"] if luks_uuid and not lvm else [*unlock, f"root=UUID={root_uuid}"]
    return " ".join([*root, *flags, "rw", *([resume] if resume else [])])


def grub_defaults(text, luks_uuid=None, resume=None):
    """/etc/default/grub with the engine's GRUB_CMDLINE_LINUX (encryption and resume)."""
    params = [*([f"cryptdevice=UUID={luks_uuid}:{CRYPT_NAME}"] if luks_uuid else []), *([resume] if resume else [])]
    lines = [line for line in text.splitlines() if not line.startswith("GRUB_CMDLINE_LINUX=")]
    return "\n".join(lines) + f'\nGRUB_CMDLINE_LINUX="{" ".join(params)}"\n'


def write_file(relative, text, mode=0o644):
    path = TARGET / relative
    if not path.resolve().is_relative_to(TARGET.resolve()):
        raise ValidationError("A settings file points outside the installed system")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


CONFIG_CHECK_FAILED = "The settings files the agent proposed did not pass the check"


def check_generated_files(config, runner):
    """Run each program's own checker on the files the model wrote (foot -C, sway -C,
    Hyprland --verify-config…), inside the installed system where the programs exist.
    A failure stops the preview before it is reported ready; the text goes to the user
    and back to the model to fix the file."""
    home = f"/home/{config.username}"
    problems = []
    runtime = TARGET / "var/tmp/agi-os-config-check"
    try:
        files = [("home", path, f"{home}/{path}") for path, _ in config.home_files]
        files += [("system", path, "/" + path) for path, _ in config.system_files]
        for scope, path, absolute in files:
            for label, binaries, args, as_user in tool_checks(scope, path):
                binary = next((b for b in binaries if (TARGET / b).is_file()), None)
                if binary is None:
                    continue  # The program is not installed: nothing reads this file.
                command = ["arch-chroot", str(TARGET)]
                if as_user:
                    if not runtime.exists():
                        runtime.mkdir(mode=0o700, parents=True)
                        runner.run([*command, "chown", f"{config.username}:{config.username}", "/" + str(runtime.relative_to(TARGET))])
                    # Compositors refuse to start as root and need a runtime directory.
                    command += ["runuser", "-u", config.username, "--", "env", f"HOME={home}",
                                "XDG_RUNTIME_DIR=/" + str(runtime.relative_to(TARGET))]
                try:
                    runner.run([*command, "/" + binary, *[a.replace("{file}", absolute) for a in args]], timeout=120)
                except ValidationError as exc:
                    detail = str(exc).split("\n", 1)[1].strip() if "\n" in str(exc) else str(exc)
                    where = ("~/" if scope == "home" else "/") + path
                    problems.append(f"{where} — {label}:\n{detail[-1200:]}" + (f"\n{HINTS[label]}" if label in HINTS else ""))
        # Keyboard layouts go into the X11/Wayland configuration; an unknown one breaks input.
        symbols = TARGET / "usr/share/X11/xkb/symbols"
        if config.session and symbols.is_dir():
            for layout in config.keyboard_layouts:
                if not (symbols / layout).is_file():
                    problems.append(f"Keyboard layout “{layout}” is not in xkeyboard-config")
    finally:
        shutil.rmtree(runtime, ignore_errors=True)
    if problems:
        raise ValidationError(CONFIG_CHECK_FAILED + ":\n" + "\n\n".join(problems))


def check_console(config):
    """The keymap and font must exist in the installed system, not only in Live."""
    kbd = TARGET / "usr/share/kbd"
    if not console_keymap_exists(config.effective_keymap(), kbd):
        raise ValidationError("The installed system has no console keymap " + config.effective_keymap())
    if not console_font_exists(config.effective_console_font(), kbd):
        raise ValidationError("The installed system has no console font " + config.effective_console_font())


def preflight(request):
    if os.geteuid() != 0 or not live_environment():
        raise ValidationError("Disks can be written only from the booted AGI OS live system")
    if set(request) - {"passphrase", "hardware", "secure_boot"} != {"configuration", "fingerprint", "consent_digest", "password"}:
        raise ValidationError("Unknown installation request")
    config = Configuration.parse(request["configuration"])
    # Inside the preview VM the site passes the real computer's inventory; a native
    # run installs for the machine it runs on.
    if request.get("hardware") is not None:
        try:
            request["hardware"] = profile(request["hardware"])
        except ValueError as exc:
            raise ValidationError(str(exc))
    if request["consent_digest"] != config.digest():
        raise ValidationError("The configuration changed after you confirmed it")
    snapshot = inventory()
    disk = selected_disk(snapshot, config.disk)
    if disk["fingerprint"] != request["fingerprint"]:
        raise ValidationError("The disk changed after you confirmed it; nothing was written")
    if snapshot["firmware"] == "bios" and config.bootloader != "grub":
        raise ValidationError("BIOS computers need the GRUB bootloader")
    layout.plan_for(config, snapshot["firmware"])  # The partition table must suit the firmware.
    if type(request.setdefault("secure_boot", False)) is not bool:
        raise ValidationError("Invalid Secure Boot choice")
    if request["secure_boot"] and (snapshot["firmware"] != "uefi" or config.bootloader != "systemd-boot"):
        raise ValidationError("Secure Boot signing works only on UEFI with the systemd-boot bootloader")
    password = request["password"]
    if not isinstance(password, str) or not 8 <= len(password) <= 256 or any(c in password for c in "\n\r\x00"):
        raise ValidationError("Enter a password of 8 to 256 characters without line breaks")
    passphrase = request.get("passphrase", "")
    if not isinstance(passphrase, str) or (passphrase and not 8 <= len(passphrase) <= 512) or any(
            c in passphrase for c in "\n\r\x00"):
        raise ValidationError("Encryption password: 8 to 512 characters without line breaks")
    supported = Path("/usr/share/i18n/SUPPORTED").read_text().splitlines()
    for locale in config.generated_locales():
        if locale + " UTF-8" not in supported:
            raise ValidationError("The selected locale is not available: " + locale)
    if TARGET.exists() and (TARGET.is_mount() or any(TARGET.iterdir())):
        raise ValidationError("A previous operation still holds the install directory; check its state first")
    tools = ("fallocate", "mkswap", "filefrag") if config.filesystem != "btrfs" else ("btrfs",)
    for command in ("sgdisk", "sfdisk", "partprobe", "udevadm", "mkfs." + config.filesystem, "cryptsetup",
                    "mkfs.fat", "pacstrap", "arch-chroot", "genfstab", "mount", "umount",
                    *(tools if config.swap == "hibernate" else ())):
        if not shutil.which(command):
            raise ValidationError("The live system is missing a tool: " + command)
    return config, snapshot, disk


def release_target(group=None):
    # pacstrap -K can leave gpg-agent holding the target keyring open. Only stop
    # daemons belonging to that keyring; never use a global pkill or lazy umount.
    keyring = TARGET / "etc/pacman.d/gnupg"
    if keyring.is_dir():
        try:
            subprocess.run(["gpgconf", "--homedir", str(keyring), "--kill", "all"],
                           capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            pass  # The real unmount below remains the authoritative check.
    result = subprocess.run(["umount", "--recursive", str(TARGET)], capture_output=True, timeout=60)
    if result.returncode:
        raise ValidationError("Could not unmount the install partitions. Keep the VM running until you check mount.")
    close_group(group)
    if Path("/dev/mapper", CRYPT_NAME).exists():
        result = subprocess.run(["cryptsetup", "close", CRYPT_NAME], capture_output=True, timeout=30)
        if result.returncode:
            raise ValidationError("Could not close the encrypted partition after installing.")


def close_group(group):
    """The root volume group goes inactive before its LUKS container closes."""
    if group and subprocess.run(["vgchange", "--activate", "n", group], capture_output=True, timeout=60).returncode:
        raise ValidationError("Could not deactivate the LVM volume group " + group + " after installing.")


def install(request, runner):
    config, snapshot, disk = preflight(request)
    hardware = request.get("hardware") or snapshot["hardware"]
    drivers = driver_plan(hardware, config.packages, config.session)
    secure_boot = request.get("secure_boot") is True
    packages = packages_for(config, hardware, secure_boot)
    hibernate = config.swap == "hibernate"
    # Sized for the computer the system is for (inside the preview: the real one, not the VM).
    swap_size = hibernation_swap_size(hardware.get("memory")) if hibernate else 0
    emit("progress", stage=4, text="Checking repositories and packages before touching the disk…")
    runner.run(["pacman", "-Sy", "--noconfirm"], timeout=180)
    catalog = Catalog()
    try:
        catalog.validate(drivers["packages"])
    except ValidationError as exc:
        raise ValidationError("An installer problem, not your choice — drivers for this hardware are missing from the repositories: " + str(exc))
    qualified = catalog.validate(packages)
    # Resolve packages before erasing. Downloads belong in the target cache,
    # rather than filling the live session's RAM-backed filesystem.
    runner.run(["pacman", "-Sp", "--noconfirm", "--", *qualified])
    # Fresh inventory is mandatory after potentially long repository requests.
    latest = selected_disk(inventory(), config.disk)
    if latest["fingerprint"] != disk["fingerprint"]:
        raise ValidationError("The disk ID changed before writing")
    if runner.cancel.is_set():
        raise Cancelled("Stopped before the disk was changed")

    firmware = snapshot["firmware"]
    passphrase = request.pop("passphrase", "")
    encrypted = bool(passphrase)
    plan = layout.plan_for(config, firmware, encrypted)
    boot = plan.path(config.disk, "boot")
    root_partition = plan.path(config.disk, "root")
    TARGET.mkdir(parents=True, exist_ok=True)
    mounted = False
    try:
        emit("progress", stage=5, text="Creating the agreed partitions on " + config.disk)
        layout.apply_table(runner, plan, config.disk, disk["size"])
        runner.run(["partprobe", config.disk])
        runner.run(["udevadm", "settle", "--timeout=30"])
        layout.format_boot(runner, plan, boot)
        if encrypted:
            emit("progress", stage=5, text="Encrypting the root partition (LUKS2)…")
        root = layout.create_root(runner, plan, root_partition, passphrase)
        passphrase = None
        layout.mount_root(runner, plan, root, TARGET)
        mounted = True
        layout.mount_boot(runner, plan, boot, TARGET)
        emit("progress", stage=5, text="Installing the base system…")
        # Install in batches and drop the download cache between them: the preview
        # image may live in memory, so its peak size must stay close to the installed size.
        chosen = set(config.packages)
        # sbctl signs every kernel it sees from its pacman and mkinitcpio hooks; it
        # comes after the base system, once its keys exist.
        late = {"sbctl"} if secure_boot else set()
        core = [q for q in qualified if q.rsplit("/", 1)[-1] not in chosen | late]
        retrying(runner, ["pacstrap", "-K", str(TARGET), *core])
        if secure_boot:
            emit("progress", stage=5, text="Creating this system’s own Secure Boot keys…")
            retrying(runner, ["arch-chroot", str(TARGET), "pacman", "-S", "--noconfirm", "--needed", "--",
                              *[q for q in qualified if q.rsplit("/", 1)[-1] in late]])
            runner.run(["arch-chroot", str(TARGET), "sbctl", "create-keys"])
        extra = [q for q in qualified if q.rsplit("/", 1)[-1] in chosen]
        for index in range(0, len(extra), BATCH):
            batch = extra[index:index + BATCH]
            emit("progress", stage=5, text=f"Installing your packages ({min(index + BATCH, len(extra))} of {len(extra)})…")
            retrying(runner, ["arch-chroot", str(TARGET), "pacman", "-S", "--noconfirm", "--needed", "--", *batch])
            trim_cache(runner)
        trim_cache(runner)

        hibernation = None
        if hibernate:
            emit("progress", stage=6, text=f"Creating the hibernation swap file ({swap_size // GIB} GiB, the size of RAM)…")
            try:
                offset = create_swapfile(runner, TARGET, config.filesystem, swap_size)
            except ValidationError as exc:
                raise ValidationError("Could not create the hibernation swap file (it needs "
                                      f"{swap_size // GIB} GiB free on the root partition): {exc}") from exc
            filesystem_uuid = runner.run(["blkid", "-s", "UUID", "-o", "value", root]).strip()
            hibernation = {"file": "/" + SWAPFILE, "size": swap_size, "resume_uuid": filesystem_uuid,
                           "resume_offset": offset, "mode": hibernate_mode(hardware)}
        resume = resume_parameter(hibernation["resume_uuid"], hibernation["resume_offset"]) if hibernation else None

        emit("progress", stage=6, text="Setting up boot, your user, the network and your desktop…")
        chroot = ["arch-chroot", str(TARGET)]
        write_file("etc/fstab", layout.fstab(runner.run(["genfstab", "-U", str(TARGET)])) + (swap_fstab_line() if hibernation else ""))
        if hibernation and hibernation["mode"] == "shutdown":
            write_file(HIBERNATE_MODE_FILE, "[Sleep]\nHibernateMode=shutdown\n")
        write_file("etc/hostname", config.hostname + "\n")
        write_file("etc/hosts", f"127.0.0.1 localhost\n::1 localhost\n127.0.1.1 {config.hostname}.localdomain {config.hostname}\n")
        write_file("etc/locale.gen", "".join(l + " UTF-8\n" for l in config.generated_locales()))
        write_file("etc/locale.conf", config.locale_conf())
        # The console font and keymap also go into the initramfs (keymap/consolefont or
        # sd-vconsole hooks), so an encryption passphrase is typed with the same keymap.
        check_console(config)
        write_file("etc/vconsole.conf", config.vconsole_conf())
        runner.run([*chroot, "ln", "-sf", "/usr/share/zoneinfo/" + config.timezone, "/etc/localtime"])
        runner.run([*chroot, "locale-gen"])
        runner.run([*chroot, "useradd", "--user-group", "--create-home", "--groups", "wheel", "--shell", "/bin/bash", config.username])
        runner.run([*chroot, "chpasswd"], input_text=config.username + ":" + request.pop("password") + "\n")
        runner.run([*chroot, "passwd", "--lock", "root"])
        write_file("etc/sudoers.d/10-agi-user", "%wheel ALL=(ALL:ALL) ALL\n", 0o440)
        runner.run([*chroot, "visudo", "--check"])
        # A Latin layout goes first: the login screen starts with the first layout and
        # a password typed there in Cyrillic would silently fail.
        layouts = ",".join(sorted(config.keyboard_layouts, key=lambda k: k != "us"))
        write_file("etc/X11/xorg.conf.d/00-keyboard.conf", 'Section "InputClass"\n'
            ' Identifier "AGI keyboard"\n MatchIsKeyboard "on"\n'
            f' Option "XkbLayout" "{layouts}"\n Option "XkbOptions" "grp:alt_shift_toggle"\nEndSection\n')
        for path, content in config.home_files:
            if not resolved(f"home/{config.username}/{path}").startswith(f"home/{config.username}/.config/"):
                raise ValidationError("A settings file points outside ~/.config: " + path)
            write_file(f"home/{config.username}/{path}", content)
        for path, content in config.system_files:
            # A symlink already in the installed tree must not redirect a model file
            # into a protected place (the validator only saw the literal path).
            if not system_path_allowed(resolved(path)):
                raise ValidationError("A system file points into a protected location: /" + path)
            write_file(path, content)
        runner.run([*chroot, "chown", "-R", config.username + ":" + config.username, "/home/" + config.username])
        check_generated_files(config, runner)
        write_file("etc/systemd/zram-generator.conf", "[zram0]\nzram-size = min(ram / 2, 8192)\ncompression-algorithm = zstd\n")
        if initramfs := initramfs_config(drivers, encrypted, hibernate, plan.lvm):
            write_file("etc/mkinitcpio.conf.d/agi-os.conf", initramfs)
        luks_uuid = runner.run(["blkid", "-s", "UUID", "-o", "value", root_partition]).strip() if encrypted else None
        time_sync = ["systemd-timesyncd.service"] if config.time_sync else []
        for service in dict.fromkeys(["NetworkManager.service", *time_sync, *drivers["services"], *config.services]):
            runner.run([*chroot, "systemctl", "enable", service])
        if not config.time_sync and "systemd-timesyncd.service" not in config.services:
            runner.run([*chroot, "systemctl", "disable", "systemd-timesyncd.service"])
        runner.run([*chroot, "systemctl", "set-default", "graphical.target" if config.session else "multi-user.target"])
        if config.session:
            sessions = [TARGET / "usr/share" / directory / (config.session + ".desktop")
                        for directory in ("xsessions", "wayland-sessions")]
            if not any(path.is_file() for path in sessions):
                raise ValidationError("The graphical session is not installed: " + config.session)
            if not (TARGET / "etc/systemd/system/display-manager.service").is_symlink():
                raise ValidationError("No display manager is enabled for the graphical session")
        runner.run([*chroot, "mkinitcpio", "-P"])
        if config.bootloader == "grub":
            if encrypted or resume:
                write_file("etc/default/grub", grub_defaults((TARGET / "etc/default/grub").read_text(), luks_uuid, resume))
            args = [*chroot, "grub-install"]
            args += (["--target=x86_64-efi", "--efi-directory=/boot", "--bootloader-id=AGIOS",
                      "--removable", "--no-nvram"] if firmware == "uefi" else ["--target=i386-pc", config.disk])
            runner.run(args)
            runner.run([*chroot, "grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
        else:
            if secure_boot:
                # bootctl installs the .signed copy when it exists; sbctl re-signs it on updates.
                runner.run([*chroot, "sbctl", "sign", "--save", "--output", SBCTL_EFI + ".signed", SBCTL_EFI])
            runner.run([*chroot, "bootctl", "--esp-path=/boot", "--no-variables", "install"])
            if secure_boot:
                runner.run([*chroot, "sbctl", "sign", "--save", "/boot/vmlinuz-linux"])
                unsigned = sbctl_unsigned(runner.run([*chroot, "sbctl", "verify"]))
                if unsigned:
                    raise ValidationError("Not signed for Secure Boot: " + ", ".join(unsigned))
            root_uuid = runner.run(["blkid", "-s", "UUID", "-o", "value", root]).strip()
            options = boot_options(root_uuid, luks_uuid, resume, layout.root_flags(plan), plan.lvm)
            write_file("boot/loader/loader.conf", "default agi-os.conf\ntimeout 3\n")
            write_file("boot/loader/entries/agi-os.conf", "title AGI OS\nlinux /vmlinuz-linux\n"
                       f"initrd /initramfs-linux.img\noptions {options}\n")
            # The fallback image carries every module: it boots the same disk on other hardware
            # (for example the preview VM after the initramfs is rebuilt for the real computer).
            write_file("boot/loader/entries/agi-os-fallback.conf", "title AGI OS (fallback initramfs)\nlinux /vmlinuz-linux\n"
                       f"initrd /initramfs-linux-fallback.img\noptions {options}\n")

        installed = set(runner.run([*chroot, "pacman", "-Qq"]).splitlines())
        if not set(packages) <= installed:
            raise ValidationError("The installed packages did not pass the check")
        runner.run([*chroot, "findmnt", "--verify", "--tab-file", "/etc/fstab"])
        record = {"id": uuid.uuid4().hex, "configuration": config.as_dict(), "packages": packages,
                  "root_uuid": runner.run(["blkid", "-s", "UUID", "-o", "value", root]).strip(),
                  "firmware": firmware, "encrypted": encrypted, "swap": config.swap, "hibernation": hibernation,
                  "secure_boot": {"signed": True, "enrolled": False} if secure_boot else None,
                  "hardware": hardware, "drivers": drivers, "settings": config.settings_record(),
                  "updates": {"timer": update.TIMER},
                  "status": "first_boot_pending"}
        write_file("var/lib/agi-os/installation.json", json.dumps(record, ensure_ascii=False, indent=2))
        write_file("usr/local/share/agi-os/verify.py", (HERE / "verify.py").read_text())
        write_file("usr/local/bin/agi-os-verify", '#!/bin/sh\nexec python /usr/local/share/agi-os/verify.py "$@"\n', 0o755)
        if config.session:
            write_file("etc/xdg/autostart/agi-os-verify.desktop", "[Desktop Entry]\nType=Application\n"
                       "Name=AGI OS — First boot\nExec=agi-os-verify --gui\nTerminal=false\n")
            write_file("usr/share/applications/agi-os-verify.desktop", "[Desktop Entry]\nType=Application\n"
                       "Name=AGI OS — Verify installation\nExec=agi-os-verify --gui\nTerminal=false\nCategories=System;\n")
        # Updates: agi-os-update, a daily check and, with a desktop, a reminder window.
        files, units = update.target_files(bool(config.session), config.bootloader)
        for path, content, mode in files:
            write_file(path, content, mode)
        for unit in units:
            runner.run([*chroot, "systemctl", "enable", unit])
        runner.run(["sync"])
    finally:
        request.pop("password", None)
        passphrase = None
        if mounted or encrypted or plan.lvm:
            # Cleanup is scoped to our mount tree, including cancellation/failure.
            original = sys.exc_info()[1]
            try:
                if mounted:
                    release_target(plan.group)
                if not mounted and plan.lvm and Path("/dev", plan.group).exists():
                    close_group(plan.group)
                if not mounted and Path("/dev/mapper", CRYPT_NAME).exists():
                    subprocess.run(["cryptsetup", "close", CRYPT_NAME], capture_output=True, timeout=30)
            except ValidationError as cleanup_error:
                if isinstance(original, (ValidationError, Cancelled)):
                    raise ValidationError(str(original) + "\n" + str(cleanup_error)) from original
                raise
    emit("installed", stage=7, text="Written and set up. Booting without the ISO is not checked yet.", record=record)


def main():
    try:
        if os.geteuid() != 0 or not live_environment():
            raise ValidationError("The install engine runs only in the AGI OS live system")
        lock = open("/run/agi-os-install.lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw = sys.stdin.readline(1_000_001)
        if len(raw) > 1_000_000:
            raise ValidationError("The request is too large")
        request = json.loads(raw)
        runner = Runner()

        def watch_cancel():
            for line in sys.stdin:
                try:
                    if json.loads(line).get("cancel") is True:
                        runner.cancel.set()
                except (ValueError, AttributeError):
                    runner.cancel.set()
            # Loss of the UI connection must not leave an unattended installation.
            runner.cancel.set()

        threading.Thread(target=watch_cancel, daemon=True).start()
        LOG.info("install.start", "Installation started")
        install(request, runner)
        LOG.info("install.done", "Installation finished")
    except (Exception, KeyboardInterrupt) as exc:
        known = isinstance(exc, (ValidationError, Cancelled))
        LOG.error("install.failed", str(exc) if known else "Internal installation error", exc=None if known else exc)
        emit("error", text=str(exc) if known
             else "The installation hit an internal error. The result is not usable.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
