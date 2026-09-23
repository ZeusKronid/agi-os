"""Offline first-use acceptance, copied to the installed OS without credentials."""

import argparse
import getpass
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path


RECORD = Path("/var/lib/agi-os/installation.json")
HIBERNATE_WAIT = 300


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout.strip()


def read(path):
    try:
        return path.read_text()
    except OSError:
        return ""


def hibernation_checks(record, state, system_root):
    """Swap file, resume parameters and the result of `agi-os-verify --hibernate`."""
    hibernation = record.get("hibernation") or {}
    checks = {}
    swaps = [line.split()[0] for line in read(system_root / "proc/swaps").splitlines()[1:] if line.split()]
    checks["Гибернация: swap-файл включён"] = hibernation.get("file") in swaps
    cmdline = read(system_root / "proc/cmdline").split()
    offset = str(hibernation.get("resume_offset"))
    checks["Гибернация: resume в параметрах ядра"] = (
        f"resume=UUID={hibernation.get('resume_uuid')}" in cmdline and f"resume_offset={offset}" in cmdline
        and read(system_root / "sys/power/resume_offset").strip() == offset
        and read(system_root / "sys/power/resume").strip() not in ("", "0:0"))
    code, answer = command(["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                            "org.freedesktop.login1.Manager", "CanHibernate"])
    checks["Гибернация: доступна системе (logind)"] = code == 0 and answer.strip() == 's "yes"'
    checks["Гибернация: сеанс восстановлен (agi-os-verify --hibernate)"] = state.get("hibernate", {}).get("result") is True
    return checks


def clocks():
    return time.time(), time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC)


def hibernate(record, state_dir=None, system_root=Path("/"), wait=HIBERNATE_WAIT):
    """Hibernate once and prove the session came back: this process and a RAM-only
    marker survive a resume, never a fresh boot. A fresh boot is detected on the next run."""
    state_dir = state_dir or Path.home() / ".local/state/agi-os" / record["id"]
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = state_dir / "acceptance.json"
    try:
        state = json.loads(state_path.read_text())
    except (FileNotFoundError, ValueError):
        state = {}
    boot_id = (system_root / "proc/sys/kernel/random/boot_id").read_text().strip()
    nonce = secrets.token_hex(8)
    marker = system_root / "dev/shm" / f"agi-os-hibernate-{os.getuid()}"
    marker.write_text(nonce)
    state["hibernate"] = {"boot_id": boot_id, "result": None}
    state_path.write_text(json.dumps(state, indent=2))
    state_path.chmod(0o600)
    wall, slept = clocks()
    code, output = command(["systemctl", "hibernate"])
    result, detail = False, "Система отказалась переходить в гибернацию: " + output if code else "Гибернация не началась"
    if not code:
        for _ in range(wait):
            time.sleep(1)
            now, now_slept = clocks()
            # The suspended time shows up as a jump of the wall clock and of CLOCK_BOOTTIME over CLOCK_MONOTONIC.
            if now_slept - slept > 1 or now - wall > 30:
                same_boot = (system_root / "proc/sys/kernel/random/boot_id").read_text().strip() == boot_id
                result = same_boot and read(marker) == nonce
                detail = "Сеанс восстановлен после гибернации" if result else "После гибернации сеанс не совпадает"
                break
            wall, slept = now, now_slept
    try:
        marker.unlink()
    except OSError:
        pass
    state["hibernate"] = {"boot_id": boot_id, "result": result, "detail": detail}
    state_path.write_text(json.dumps(state, indent=2))
    return result, detail


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
    if state.get("hibernate", {}).get("result") is None and state.get("hibernate", {}).get("boot_id") not in (None, boot_id):
        # agi-os-verify --hibernate never saw its session again: the computer booted afresh.
        state["hibernate"] = {"boot_id": boot_id, "result": False,
                              "detail": "После гибернации система загрузилась заново: сеанс не восстановлен"}
    checks = {}
    checks["Вход под созданным пользователем"] = getpass.getuser() == config["username"]
    checks["Загрузка с установленного диска"] = command(["findmnt", "-n", "-o", "UUID", "/"])[1] == record["root_uuid"]
    checks["Live-среда отключена"] = not (system_root / "run/archiso/bootmnt").is_mount()
    checks["Файловая система"] = command(["findmnt", "-n", "-o", "FSTYPE", "/"])[1] == config["filesystem"]
    checks["Имя компьютера"] = socket.gethostname() == config["hostname"]
    checks["Часовой пояс"] = (system_root / "etc/localtime").resolve() == (system_root / "usr/share/zoneinfo" / config["timezone"]).resolve()
    checks["Язык системы"] = "LANG=" + config["locale"] in (system_root / "etc/locale.conf").read_text().splitlines()
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
    if config["session"]:
        actual = " ".join(os.environ.get(k, "") for k in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION", "XDG_SESSION_DESKTOP"))
        checks["Выбранная графическая сессия"] = config["session"].casefold() in actual.casefold()
    if record.get("hibernation"):
        checks.update(hibernation_checks(record, state, system_root))
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
            "hibernate": state.get("hibernate"),
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
    sleep_button = None
    if record.get("hibernation"):
        sleep_button = Gtk.Button(label="Проверить гибернацию (компьютер выключится и восстановит этот сеанс)")
        box.pack_start(sleep_button, False, False, 0)
    hint = Gtk.Label(label="Для проверки сохранности файлов нужна ещё одна перезагрузка.\n"
                    "В окружениях без автозапуска откройте agi-os-verify --gui повторно."
                    + ("\nГибернация была выбрана при установке, поэтому проверка завершится только после "
                       "успешной пробной гибернации (кнопка выше или agi-os-verify --hibernate)."
                       if record.get("hibernation") else ""), xalign=0)
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

    def test_hibernation(_):
        sleep_button.set_sensitive(False)
        button.set_sensitive(False)
        output.get_buffer().set_text("Перехожу в гибернацию. Включите компьютер снова, когда он выключится.")
        def work():
            try:
                hibernate(record)
            except Exception:
                pass
            GLib.idle_add(sleep_button.set_sensitive, True)
            GLib.idle_add(refresh, None, True)
        threading.Thread(target=work, daemon=True).start()
    if sleep_button:
        sleep_button.connect("clicked", test_hibernation)
    window.show_all()
    refresh(None, True)
    Gtk.main()


def main():
    parser = argparse.ArgumentParser(description="Verify AGI OS first boot and user requirements")
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--confirm", action="store_true", help="Confirm that you tested all listed user requirements")
    parser.add_argument("--hibernate", action="store_true", help="Hibernate once and check that this session is restored")
    args = parser.parse_args()
    try:
        record = json.loads(RECORD.read_text())
        if args.hibernate:
            if not record.get("hibernation"):
                print("Гибернация не настраивалась при установке (swap: zram).", file=sys.stderr)
                return 2
            print("Перехожу в гибернацию. Когда компьютер выключится, включите его снова.", flush=True)
            passed, detail = hibernate(record)
            print(detail)
            return 0 if passed else 1
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
