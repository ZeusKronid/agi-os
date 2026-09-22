"""Privileged installation worker. Only runs inside an Archiso live boot.

Input: one validated configuration/consent/password record on stdin (with an
optional private LUKS passphrase), followed optionally by {"cancel": true}.
Output: secret-free JSONL progress events. No shell code or provider
credentials are accepted by this process.
"""

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from domain import Configuration, ValidationError
from system import Catalog, inventory, live_environment, selected_disk


TARGET = Path("/mnt/agi-os")
HERE = Path(__file__).resolve().parent
BASE_PACKAGES = ("base", "linux", "linux-firmware", "networkmanager", "sudo", "python",
                 "intel-ucode", "amd-ucode", "zram-generator")
CRYPT_NAME = "cryptroot"
# The udev-based default HOOKS of mkinitcpio.conf plus `encrypt` before filesystems.
ENCRYPT_HOOKS = ("HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont "
                 "block encrypt filesystems fsck)\n")


def emit(kind, **data):
    print(json.dumps({"kind": kind, **data}, ensure_ascii=False), flush=True)


class Cancelled(RuntimeError):
    pass


class Runner:
    def __init__(self):
        self.cancel = threading.Event()

    def run(self, args, input_text=None, timeout=1800):
        if self.cancel.is_set():
            raise Cancelled("Установка остановлена. Диск мог быть частично изменён.")
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
                        raise Cancelled("Установка остановлена; на диске осталась частичная установка.")
                    raise ValidationError(f"Истекло время операции {args[0]}")
        if proc.returncode:
            # Never echo input to a credential operation, even if a subprocess does so.
            detail = "" if input_text is not None else output[-2500:]
            raise ValidationError(f"Ошибка {args[0]} (код {proc.returncode})\n{detail}")
        return output


def partition_path(disk, number):
    return disk + ("p" if disk[-1].isdigit() else "") + str(number)


def packages_for(config):
    packages = [*BASE_PACKAGES, config.filesystem + "-progs" if config.filesystem == "btrfs"
                else {"ext4": "e2fsprogs", "xfs": "xfsprogs", "f2fs": "f2fs-tools"}[config.filesystem],
                *config.packages]
    if config.bootloader == "grub":
        packages += ["grub", "efibootmgr"]
    if config.session:
        packages += ["python-gobject", "gtk3"]
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
            emit("progress", stage=5, text=f"Повторяю загрузку пакетов (попытка {attempt + 1} из {attempts})…")
            time.sleep(10 * attempt)


def trim_cache(runner):
    # Package archives never compress further; keeping them would double an in-memory preview.
    runner.run(["arch-chroot", str(TARGET), "pacman", "-Scc", "--noconfirm"])
    try:
        runner.run(["fstrim", str(TARGET)], timeout=300)
    except ValidationError:
        pass  # Media without discard support simply keep their blocks allocated.


def write_file(relative, text, mode=0o644):
    path = TARGET / relative
    if not path.resolve().is_relative_to(TARGET.resolve()):
        raise ValidationError("Файл настроек выходит за пределы установленной системы")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


def preflight(request):
    if os.geteuid() != 0 or not live_environment():
        raise ValidationError("Запись дисков разрешена только в загруженной live-системе AGI OS")
    if set(request) - {"passphrase"} != {"configuration", "fingerprint", "consent_digest", "password"}:
        raise ValidationError("Неизвестный запрос установки")
    config = Configuration.parse(request["configuration"])
    if request["consent_digest"] != config.digest():
        raise ValidationError("Конфигурация изменилась после подтверждения")
    snapshot = inventory()
    disk = selected_disk(snapshot, config.disk)
    if disk["fingerprint"] != request["fingerprint"]:
        raise ValidationError("Диск изменился после подтверждения; запись отменена")
    if snapshot["firmware"] == "bios" and config.bootloader != "grub":
        raise ValidationError("Для BIOS требуется загрузчик GRUB")
    password = request["password"]
    if not isinstance(password, str) or not 8 <= len(password) <= 256 or any(c in password for c in "\n\r\x00"):
        raise ValidationError("Введите пароль длиной от 8 до 256 символов без переносов строк")
    passphrase = request.get("passphrase", "")
    if not isinstance(passphrase, str) or (passphrase and not 8 <= len(passphrase) <= 512) or any(
            c in passphrase for c in "\n\r\x00"):
        raise ValidationError("Пароль шифрования: от 8 до 512 символов без переносов строк")
    supported = Path("/usr/share/i18n/SUPPORTED").read_text().splitlines()
    if config.locale + " UTF-8" not in supported:
        raise ValidationError("Выбранная локаль недоступна")
    if TARGET.exists() and (TARGET.is_mount() or any(TARGET.iterdir())):
        raise ValidationError("Каталог установки занят предыдущей операцией; нужна проверка её состояния")
    for command in ("sgdisk", "partprobe", "udevadm", "mkfs." + config.filesystem, "cryptsetup",
                    "mkfs.fat", "pacstrap", "arch-chroot", "genfstab", "mount", "umount"):
        if not shutil.which(command):
            raise ValidationError("В live-системе отсутствует инструмент: " + command)
    return config, snapshot, disk


def release_target():
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
        raise ValidationError("Не удалось отключить разделы установки. Не выключайте VM до проверки mount.")
    if Path("/dev/mapper", CRYPT_NAME).exists():
        result = subprocess.run(["cryptsetup", "close", CRYPT_NAME], capture_output=True, timeout=30)
        if result.returncode:
            raise ValidationError("Не удалось закрыть зашифрованный раздел после установки.")


def install(request, runner):
    config, snapshot, disk = preflight(request)
    packages = packages_for(config)
    emit("progress", stage=4, text="Проверяю репозитории и пакеты до изменения диска…")
    runner.run(["pacman", "-Sy", "--noconfirm"], timeout=180)
    qualified = Catalog().validate(packages)
    # Resolve packages before erasing. Downloads belong in the target cache,
    # rather than filling the live session's RAM-backed filesystem.
    runner.run(["pacman", "-Sp", "--noconfirm", "--", *qualified])
    # Fresh inventory is mandatory after potentially long repository requests.
    latest = selected_disk(inventory(), config.disk)
    if latest["fingerprint"] != disk["fingerprint"]:
        raise ValidationError("Идентификатор диска изменился до записи")
    if runner.cancel.is_set():
        raise Cancelled("Остановлено до изменения диска")

    firmware = snapshot["firmware"]
    boot_number, root_number = (1, 2) if firmware == "uefi" else (2, 3)
    boot = partition_path(config.disk, boot_number)
    root_partition = partition_path(config.disk, root_number)
    passphrase = request.pop("passphrase", "")
    encrypted = bool(passphrase)
    root = "/dev/mapper/" + CRYPT_NAME if encrypted else root_partition
    TARGET.mkdir(parents=True, exist_ok=True)
    mounted = False
    try:
        emit("progress", stage=5, text="Создаю согласованные разделы на " + config.disk)
        runner.run(["sgdisk", "--zap-all", config.disk])
        args = ["sgdisk"]
        if firmware == "bios":
            args += ["--new=1:0:+2M", "--typecode=1:ef02", "--change-name=1:BIOS"]
        args += [f"--new={boot_number}:0:+1G", f"--typecode={boot_number}:" + ("ef00" if firmware == "uefi" else "8300"),
                 f"--change-name={boot_number}:AGI-BOOT", f"--new={root_number}:0:0",
                 f"--typecode={root_number}:8300", f"--change-name={root_number}:AGI-ROOT", config.disk]
        runner.run(args)
        runner.run(["partprobe", config.disk])
        runner.run(["udevadm", "settle", "--timeout=30"])
        runner.run(["mkfs.fat", "-F", "32", boot] if firmware == "uefi" else ["mkfs.ext4", "-F", boot])
        if encrypted:
            emit("progress", stage=5, text="Шифрую корневой раздел (LUKS2)…")
            # The passphrase travels only over stdin; a trailing newline would become part of the key.
            runner.run(["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", "--key-file", "-",
                        root_partition], input_text=passphrase)
            runner.run(["cryptsetup", "open", "--key-file", "-", root_partition, CRYPT_NAME], input_text=passphrase)
        passphrase = None
        force = {"ext4": "-F", "btrfs": "-f", "xfs": "-f", "f2fs": "-f"}[config.filesystem]
        runner.run(["mkfs." + config.filesystem, force, root])
        runner.run(["mount", root, str(TARGET)])
        mounted = True
        (TARGET / "boot").mkdir()
        runner.run(["mount", boot, str(TARGET / "boot")])
        emit("progress", stage=5, text="Устанавливаю базовую систему…")
        # Install in batches and drop the download cache between them: the preview
        # image may live in memory, so its peak size must stay close to the installed size.
        chosen = set(config.packages)
        core = [q for q in qualified if q.rsplit("/", 1)[-1] not in chosen]
        retrying(runner, ["pacstrap", "-K", str(TARGET), *core])
        extra = [q for q in qualified if q.rsplit("/", 1)[-1] in chosen]
        for index in range(0, len(extra), BATCH):
            batch = extra[index:index + BATCH]
            emit("progress", stage=5, text=f"Устанавливаю выбранные пакеты ({min(index + BATCH, len(extra))} из {len(extra)})…")
            retrying(runner, ["arch-chroot", str(TARGET), "pacman", "-S", "--noconfirm", "--needed", "--", *batch])
            trim_cache(runner)
        trim_cache(runner)

        emit("progress", stage=6, text="Настраиваю загрузку, пользователя, сеть и выбранное окружение…")
        chroot = ["arch-chroot", str(TARGET)]
        write_file("etc/fstab", runner.run(["genfstab", "-U", str(TARGET)]))
        write_file("etc/hostname", config.hostname + "\n")
        write_file("etc/hosts", f"127.0.0.1 localhost\n::1 localhost\n127.0.1.1 {config.hostname}.localdomain {config.hostname}\n")
        locales = list(dict.fromkeys(["en_US.UTF-8", config.locale]))
        write_file("etc/locale.gen", "".join(l + " UTF-8\n" for l in locales))
        write_file("etc/locale.conf", "LANG=" + config.locale + "\n")
        write_file("etc/vconsole.conf", "KEYMAP=us\n")
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
            write_file(f"home/{config.username}/{path}", content)
        for path, content in config.system_files:
            write_file(path, content)
        runner.run([*chroot, "chown", "-R", config.username + ":" + config.username, "/home/" + config.username])
        write_file("etc/systemd/zram-generator.conf", "[zram0]\nzram-size = min(ram / 2, 8192)\ncompression-algorithm = zstd\n")
        kernel_options = "rw"
        if encrypted:
            write_file("etc/mkinitcpio.conf.d/agi-encrypt.conf", ENCRYPT_HOOKS)
            luks_uuid = runner.run(["blkid", "-s", "UUID", "-o", "value", root_partition]).strip()
            kernel_options = f"cryptdevice=UUID={luks_uuid}:{CRYPT_NAME} root={root} rw"
        for service in dict.fromkeys(["NetworkManager.service", "systemd-timesyncd.service", *config.services]):
            runner.run([*chroot, "systemctl", "enable", service])
        runner.run([*chroot, "systemctl", "set-default", "graphical.target" if config.session else "multi-user.target"])
        if config.session:
            sessions = [TARGET / "usr/share" / directory / (config.session + ".desktop")
                        for directory in ("xsessions", "wayland-sessions")]
            if not any(path.is_file() for path in sessions):
                raise ValidationError("Указанная графическая сессия не установлена: " + config.session)
            if not (TARGET / "etc/systemd/system/display-manager.service").is_symlink():
                raise ValidationError("Для графической сессии не включён дисплейный менеджер")
        runner.run([*chroot, "mkinitcpio", "-P"])
        if config.bootloader == "grub":
            if encrypted:
                defaults = (TARGET / "etc/default/grub").read_text()
                write_file("etc/default/grub", defaults + f'\nGRUB_CMDLINE_LINUX="cryptdevice=UUID={luks_uuid}:{CRYPT_NAME}"\n')
            args = [*chroot, "grub-install"]
            args += (["--target=x86_64-efi", "--efi-directory=/boot", "--bootloader-id=AGIOS",
                      "--removable", "--no-nvram"] if firmware == "uefi" else ["--target=i386-pc", config.disk])
            runner.run(args)
            runner.run([*chroot, "grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
        else:
            runner.run([*chroot, "bootctl", "--esp-path=/boot", "--no-variables", "install"])
            root_uuid = runner.run(["blkid", "-s", "UUID", "-o", "value", root]).strip()
            options = kernel_options if encrypted else f"root=UUID={root_uuid} rw"
            write_file("boot/loader/loader.conf", "default agi-os.conf\ntimeout 3\n")
            write_file("boot/loader/entries/agi-os.conf", "title AGI OS\nlinux /vmlinuz-linux\n"
                       f"initrd /initramfs-linux.img\noptions {options}\n")
            # The fallback image carries every module: it boots the same disk on other hardware
            # (for example the preview VM after the initramfs is rebuilt for the real computer).
            write_file("boot/loader/entries/agi-os-fallback.conf", "title AGI OS (fallback initramfs)\nlinux /vmlinuz-linux\n"
                       f"initrd /initramfs-linux-fallback.img\noptions {options}\n")

        installed = set(runner.run([*chroot, "pacman", "-Qq"]).splitlines())
        if not set(packages) <= installed:
            raise ValidationError("Проверка установленных пакетов не пройдена")
        runner.run([*chroot, "findmnt", "--verify", "--tab-file", "/etc/fstab"])
        record = {"id": uuid.uuid4().hex, "configuration": config.as_dict(), "packages": packages,
                  "root_uuid": runner.run(["blkid", "-s", "UUID", "-o", "value", root]).strip(),
                  "firmware": firmware, "encrypted": encrypted, "swap": "zram",
                  "status": "first_boot_pending"}
        write_file("var/lib/agi-os/installation.json", json.dumps(record, ensure_ascii=False, indent=2))
        write_file("usr/local/share/agi-os/verify.py", (HERE / "verify.py").read_text())
        write_file("usr/local/bin/agi-os-verify", '#!/bin/sh\nexec python /usr/local/share/agi-os/verify.py "$@"\n', 0o755)
        if config.session:
            write_file("etc/xdg/autostart/agi-os-verify.desktop", "[Desktop Entry]\nType=Application\n"
                       "Name=AGI OS — First boot\nExec=agi-os-verify --gui\nTerminal=false\n")
            write_file("usr/share/applications/agi-os-verify.desktop", "[Desktop Entry]\nType=Application\n"
                       "Name=AGI OS — Verify installation\nExec=agi-os-verify --gui\nTerminal=false\nCategories=System;\n")
        runner.run(["sync"])
    finally:
        request.pop("password", None)
        passphrase = None
        if mounted or encrypted:
            # Cleanup is scoped to our mount tree, including cancellation/failure.
            original = sys.exc_info()[1]
            try:
                if mounted:
                    release_target()
                elif Path("/dev/mapper", CRYPT_NAME).exists():
                    subprocess.run(["cryptsetup", "close", CRYPT_NAME], capture_output=True, timeout=30)
            except ValidationError as cleanup_error:
                if isinstance(original, (ValidationError, Cancelled)):
                    raise ValidationError(str(original) + "\n" + str(cleanup_error)) from original
                raise
    emit("installed", stage=7, text="Запись и настройка завершены. Загрузка без ISO ещё не проверена.", record=record)


def main():
    try:
        if os.geteuid() != 0 or not live_environment():
            raise ValidationError("Установочный движок запускается только в live-системе AGI OS")
        lock = open("/run/agi-os-install.lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw = sys.stdin.readline(1_000_001)
        if len(raw) > 1_000_000:
            raise ValidationError("Запрос слишком большой")
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
        install(request, runner)
    except (Exception, KeyboardInterrupt) as exc:
        emit("error", text=str(exc) if isinstance(exc, (ValidationError, Cancelled))
             else "Установка прервана внутренней ошибкой. Результат не считается готовым.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
