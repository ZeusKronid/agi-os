"""Offline first-use acceptance, copied to the installed OS without credentials."""

import argparse
import getpass
import json
import os
import socket
import subprocess
import sys
from pathlib import Path


RECORD = Path("/var/lib/agi-os/installation.json")


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return result.returncode, result.stdout.strip()


SECURE_BOOT_VAR = "SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
SIGNED_BOOT_FILES = ("boot/EFI/BOOT/BOOTX64.EFI", "boot/EFI/systemd/systemd-bootx64.efi", "boot/vmlinuz-linux")


def pe_signed(path):
    """True when a PE/EFI image carries an Authenticode certificate table (data directory 4)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    if data[:2] != b"MZ":
        return False
    pe = int.from_bytes(data[0x3C:0x40], "little")
    if data[pe:pe + 4] != b"PE\0\0":
        return False
    optional = pe + 24
    directories = optional + (112 if int.from_bytes(data[optional:optional + 2], "little") == 0x20B else 96)
    return int.from_bytes(data[directories + 36:directories + 40], "little") > 0


def secure_boot_enabled(system_root=Path("/")):
    try:
        return (system_root / "sys/firmware/efi/efivars" / SECURE_BOOT_VAR).read_bytes()[4:5] == b"\x01"
    except OSError:
        return False
def conf_values(path):
    values = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return values
    for line in lines:
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            values[key] = value.strip().strip('"')
    return values


def normalized_locale(name):
    # `locale -a` prints ru_RU.utf8 for ru_RU.UTF-8.
    base, _, codeset = name.partition(".")
    return base + "." + codeset.lower().replace("-", "") if codeset else base


def regional_checks(settings, locale_conf, system_root, graphical):
    checks = {}
    formats = [line for line in settings["locale_conf"] if line.startswith("LC_")]
    if formats:
        checks["Форматы: " + ", ".join(formats)] = set(formats) <= set(locale_conf)
    available = {normalized_locale(l) for l in command(["locale", "-a"])[1].splitlines()}
    checks["Локали сгенерированы: " + ", ".join(settings["locales"])] = all(
        normalized_locale(l) in available for l in settings["locales"])
    vconsole = conf_values(system_root / "etc/vconsole.conf")
    kbd = system_root / "usr/share/kbd"
    checks["Консоль: раскладка " + settings["keymap"]] = vconsole.get("KEYMAP") == settings["keymap"] and any(
        kbd.glob(f"keymaps/**/{settings['keymap']}.map.gz"))
    checks["Консоль: шрифт " + settings["console_font"]] = vconsole.get("FONT") == settings["console_font"] and any(
        kbd.glob(f"consolefonts/{settings['console_font']}.*"))
    if graphical and settings["fonts"]:
        code, families = command(["fc-list", ":", "family"])
        checks["Шрифты интерфейса установлены"] = code == 0 and bool(families)
        if settings.get("cyrillic"):
            checks["Шрифт с кириллицей для интерфейса"] = bool(command(["fc-list", ":lang=ru", "family"])[1])
    if settings["time_sync"]:
        checks["Синхронизация времени (NTP)"] = command(["systemctl", "is-enabled", "systemd-timesyncd.service"])[0] == 0
    return checks


def evaluate(record, state_dir=None, confirm=False, system_root=Path("/")):
    config = record["configuration"]
    state_dir = state_dir or Path.home() / ".local/state/agi-os" / record["id"]
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = state_dir / "acceptance.json"
    marker_path = state_dir / "persistence-check.txt"
    try:
        state = json.loads(state_path.read_text())
    except (FileNotFoundError, ValueError):
        state = {}
    boot_id = (system_root / "proc/sys/kernel/random/boot_id").read_text().strip()
    checks = {}
    checks["Вход под созданным пользователем"] = getpass.getuser() == config["username"]
    checks["Загрузка с установленного диска"] = command(["findmnt", "-n", "-o", "UUID", "/"])[1] == record["root_uuid"]
    checks["Live-среда отключена"] = not (system_root / "run/archiso/bootmnt").is_mount()
    checks["Файловая система"] = command(["findmnt", "-n", "-o", "FSTYPE", "/"])[1] == config["filesystem"]
    checks["Имя компьютера"] = socket.gethostname() == config["hostname"]
    checks["Часовой пояс"] = (system_root / "etc/localtime").resolve() == (system_root / "usr/share/zoneinfo" / config["timezone"]).resolve()
    locale_conf = (system_root / "etc/locale.conf").read_text().splitlines()
    checks["Язык системы"] = "LANG=" + config["locale"] in locale_conf
    settings = record.get("settings")
    if settings:
        checks.update(regional_checks(settings, locale_conf, system_root, bool(config["session"])))
    installed = set(command(["pacman", "-Qq"])[1].splitlines())
    checks["Все выбранные пакеты"] = set(record["packages"]) <= installed
    drivers = record.get("drivers") or {}
    if drivers.get("packages"):
        checks["Драйверы под железо компьютера"] = set(drivers["packages"]) <= installed
    for service in dict.fromkeys(["NetworkManager.service", *drivers.get("services", []), *config["services"]]):
        checks["Автозапуск: " + service] = command(["systemctl", "is-enabled", service])[0] == 0
    checks["Сеть: NetworkManager"] = command(["systemctl", "is-active", "NetworkManager.service"])[0] == 0
    try:
        socket.getaddrinfo("archlinux.org", 443)
        checks["Сеть: DNS"] = True
    except OSError:
        checks["Сеть: DNS"] = False
    secure_boot = record.get("secure_boot") or {}
    if secure_boot.get("signed"):
        checks["Secure Boot: загрузчик и ядро подписаны"] = all(pe_signed(system_root / f) for f in SIGNED_BOOT_FILES)
        if secure_boot.get("enrolled"):
            checks["Secure Boot включён в прошивке"] = secure_boot_enabled(system_root)
    if config["session"]:
        actual = " ".join(os.environ.get(k, "") for k in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "XDG_SESSION_DESKTOP"))
        checks["Выбранная графическая сессия"] = config["session"].casefold() in actual.casefold()
    correct_system = all(checks[k] for k in ("Вход под созданным пользователем", "Загрузка с установленного диска", "Live-среда отключена"))
    persisted = marker_path.is_file() and marker_path.read_text() == record["id"]
    second_boot = bool(state.get("first_boot") and state["first_boot"] != boot_id and persisted)
    checks["Файл сохранён после повторной загрузки"] = second_boot
    if correct_system:
        if "first_boot" not in state:
            marker_path.write_text(record["id"])
            state["first_boot"] = boot_id
        if confirm:
            state["user_checked_requirements"] = True
        state["complete"] = all(checks.values()) and state.get("user_checked_requirements", False)
        state_path.write_text(json.dumps(state, indent=2))
        state_path.chmod(0o600)
    return {"checks": checks, "requirements": config["requirements"], "warnings": record.get("warnings", []),
            "user_checked_requirements": bool(state.get("user_checked_requirements")),
            "complete": correct_system and all(checks.values()) and bool(state.get("user_checked_requirements")),
            "report": str(state_path)}


def gui(record):
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, GLib
    import threading
    window = Gtk.Window(title="AGI OS — Проверка новой системы")
    window.set_default_size(720, 640)
    window.set_border_width(24)
    window.connect("destroy", Gtk.main_quit)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
    window.add(box)
    title = Gtk.Label(label="Этапы 7–8 · Проверка установленной системы", xalign=0)
    box.pack_start(title, False, False, 0)
    output = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
    scroll = Gtk.ScrolledWindow()
    scroll.add(output)
    box.pack_start(scroll, True, True, 0)
    checked = Gtk.CheckButton(label="Я проверил приложения, раскладки и все согласованные требования")
    box.pack_start(checked, False, False, 0)
    button = Gtk.Button(label="Проверить и сохранить результат")
    box.pack_start(button, False, False, 0)
    hint = Gtk.Label(label="Для проверки сохранности файлов нужна ещё одна перезагрузка.\n"
                    "В окружениях без автозапуска откройте agi-os-verify --gui повторно.", xalign=0)
    hint.set_line_wrap(True)
    box.pack_start(hint, False, False, 0)

    def update(result):
        button.set_sensitive(True)
        if isinstance(result, str):
            output.get_buffer().set_text(result)
            return
        text = "\n".join(("✓ " if passed else "○ Не подтверждено: ") + name for name, passed in result["checks"].items())
        if result.get("warnings"):
            text += "\n\nЗамечания установки:\n" + "\n".join("• " + item for item in result["warnings"])
        text += "\n\nПроверьте вручную:\n" + "\n".join("• " + item for item in result["requirements"])
        text += "\n\n" + ("Установка проверена." if result["complete"] else "Проверка ещё не завершена.")
        output.get_buffer().set_text(text)
        checked.set_active(result["user_checked_requirements"])

    def refresh(_, automatic=False):
        consent = checked.get_active() and not automatic
        button.set_sensitive(False)
        def work():
            try:
                result = evaluate(record, confirm=consent)
            except Exception:
                result = "Не удалось закончить проверку. Установка не отмечена как проверенная."
            GLib.idle_add(update, result)
        threading.Thread(target=work, daemon=True).start()
    button.connect("clicked", refresh)
    window.show_all()
    refresh(None, True)
    Gtk.main()


def main():
    parser = argparse.ArgumentParser(description="Verify AGI OS first boot and user requirements")
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--confirm", action="store_true", help="Confirm that you tested all listed user requirements")
    args = parser.parse_args()
    try:
        record = json.loads(RECORD.read_text())
        if args.gui:
            gui(record)
            return 0
        result = evaluate(record, confirm=args.confirm)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["complete"] else 1
    except Exception:
        print("Проверка не выполнена: нет корректной записи установки или доступа к системе.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
