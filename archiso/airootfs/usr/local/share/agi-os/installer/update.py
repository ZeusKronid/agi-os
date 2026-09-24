"""Updates for the installed AGI OS, copied to the target as agi-os-update.

check   (root, daily timer) refreshes a private copy of the sync databases and
        records the pending updates without touching the system's own databases,
        so a later `pacman -S` can never become a partial upgrade.
apply   (root) one complete, checked update: power and free space first, a btrfs
        snapshot of the root, the keyring before everything else, then
        `pacman -Su`; bootloader refresh, `.pacnew` files and "reboot needed" after.
--gui   (user) the same as a window: the list, one button, the password only
        on sudo's stdin.

Nothing here reads provider credentials or talks to a model.
"""

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


STATE = Path("/var/lib/agi-os")
STATUS = STATE / "update-status.json"
NOTICE = STATE / "update-notice"
SYNC_DB = STATE / "update-db"
LOG = Path("/var/log/agi-os/update.log")
RECORD = STATE / "installation.json"
LOCK = Path("/run/agi-os-update.lock")
PACMAN_DB = Path("/var/lib/pacman")
SNAPSHOTS = Path("/.snapshots")
SNAPSHOT_PREFIX = "pre-update-"
KEEP_SNAPSHOTS = 3
MIN_FREE = 2 * 1024 ** 3
MIN_BATTERY = 30
KERNELS = {"linux", "linux-lts", "linux-zen", "linux-hardened", "linux-rt", "linux-rt-lts"}
REBOOT_PACKAGES = KERNELS | {"amd-ucode", "intel-ucode", "systemd", "glibc"}
TIMER = "agi-os-update-check.timer"
NOTIFY_STATE = Path(".local/state/agi-os/update-notified")


class UpdateError(RuntimeError):
    pass


def run(args, timeout=600, input_text=None):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=input_text,
                            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    if result.returncode:
        detail = (result.stdout + result.stderr).strip()[-2000:]
        raise UpdateError(f"{args[0]} failed (code {result.returncode})\n{detail}")
    return result.stdout


def stream(args):
    """Run with the output shown as it comes (pacman can take many minutes); the tail goes into the error."""
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    tail = []
    for line in proc.stdout:
        print(line, end="", flush=True)
        tail = (tail + [line])[-40:]
    if proc.wait():
        detail = "".join(tail).strip()[-2000:]
        log(f"{args[0]}: code {proc.returncode}\n{detail}")
        raise UpdateError(f"{args[0]} failed (code {proc.returncode})\n{detail}")


def boot_id(proc=Path("/proc")):
    try:
        return (proc / "sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def log(line):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 1024 ** 2:
            LOG.write_text(LOG.read_text(errors="replace")[-256 * 1024:])
        with LOG.open("a") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line.rstrip() + "\n")
    except OSError:
        pass


def parse_updates(text):
    """`pacman -Qu` lines: "name old -> new"; ignored packages carry a trailing [ignored]."""
    updates = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[2] == "->":
            updates.append({"name": parts[0], "old": parts[1], "new": parts[3]})
    return updates


def installed_versions():
    return dict(line.split(None, 1) for line in run(["pacman", "-Q"]).splitlines() if " " in line)


def changed_packages(before, after):
    return sorted(name for name, version in after.items() if before.get(name) != version)


def read_status(path=None):
    try:
        return json.loads((path or STATUS).read_text())
    except (OSError, ValueError):
        return {}


def notice_text(status):
    lines = []
    count = len(status.get("updates", []))
    if count:
        lines.append(f"AGI OS: updates available: {count}" + (" (including the kernel)" if status.get("kernel") else "")
                     + ". Install: sudo agi-os-update apply")
    if status.get("reboot_required"):
        lines.append("AGI OS: an update is installed; restart the computer to apply it fully.")
    if status.get("pacnew"):
        lines.append("AGI OS: new versions of settings files are available (.pacnew): " + ", ".join(status["pacnew"][:5])
                     + ". Compare them with the current files and carry over the changes you need.")
    return "".join(line + "\n" for line in lines)


def write_status(status, state=None):
    state = state or STATE
    state.mkdir(parents=True, exist_ok=True)
    for path, text in ((state / STATUS.name, json.dumps(status, ensure_ascii=False, indent=2)),
                       (state / NOTICE.name, notice_text(status))):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(text)
        temporary.chmod(0o644)
        temporary.replace(path)


def require_root():
    if os.geteuid() != 0:
        raise UpdateError("Administrator rights needed: sudo agi-os-update " + " ".join(sys.argv[1:]))


def locked():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise UpdateError("An update check or installation is already running") from None
    return handle


def check(db=None, pacman_db=None):
    """Pending updates against fresh repositories, using a private sync database."""
    db, pacman_db = db or SYNC_DB, pacman_db or PACMAN_DB
    db.mkdir(parents=True, exist_ok=True)
    local = db / "local"
    if not local.is_symlink():
        if local.exists():
            raise UpdateError("The update check’s private database is damaged: " + str(local))
        local.symlink_to(pacman_db / "local")
    run(["pacman", "-Sy", "--dbpath", str(db), "--logfile", "/dev/null"], timeout=600)
    result = subprocess.run(["pacman", "-Qu", "--dbpath", str(db)], capture_output=True, text=True,
                            timeout=120, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    # pacman -Qu exits 1 when nothing is outdated.
    if result.returncode not in (0, 1):
        raise UpdateError("Could not compare package versions")
    updates = parse_updates(result.stdout)
    return {"updates": updates, "kernel": any(u["name"] in KERNELS for u in updates)}


def on_battery_below(limit=MIN_BATTERY, supplies=Path("/sys/class/power_supply")):
    """The lowest charge of a discharging battery below the limit, else None."""
    if not supplies.is_dir():
        return None
    for supply in supplies.iterdir():
        try:
            if (supply / "type").read_text().strip() != "Battery":
                continue
            if (supply / "status").read_text().strip() != "Discharging":
                continue
            capacity = int((supply / "capacity").read_text().strip())
        except (OSError, ValueError):
            continue
        if capacity < limit:
            return capacity
    return None


def free_bytes(path):
    stats = os.statvfs(path)
    return stats.f_bavail * stats.f_frsize


def root_filesystem():
    return subprocess.run(["findmnt", "-n", "-o", "FSTYPE", "/"], capture_output=True, text=True).stdout.strip()


def snapshot(stamp, snapshots=None, keep=KEEP_SNAPSHOTS):
    """Read-only btrfs snapshot of the root; the oldest pre-update snapshots beyond `keep` go."""
    snapshots = snapshots or SNAPSHOTS
    if not snapshots.exists():
        run(["btrfs", "subvolume", "create", str(snapshots)])
    target = snapshots / (SNAPSHOT_PREFIX + stamp)
    run(["btrfs", "subvolume", "snapshot", "-r", "/", str(target)])
    old = sorted(p for p in snapshots.iterdir() if p.name.startswith(SNAPSHOT_PREFIX))[:-keep]
    for path in old:
        try:
            run(["btrfs", "subvolume", "delete", str(path)])
        except UpdateError:
            log("Could not delete the old snapshot " + str(path))
    return str(target)


def bootloader(record_path=None, boot=Path("/boot")):
    try:
        return json.loads((record_path or RECORD).read_text())["configuration"]["bootloader"]
    except (OSError, ValueError, KeyError, TypeError):
        return "systemd-boot" if (boot / "loader/loader.conf").exists() else "grub"


def refresh_bootloader(kind, changed, firmware=None):
    """Re-deploy the bootloader binary after its package changed; kernels need nothing:
    the entries point to fixed /boot paths and mkinitcpio's hook rebuilt the images."""
    done = []
    if kind == "systemd-boot" and "systemd" in changed:
        run(["bootctl", "--graceful", "update"])
        done.append("systemd-boot")
    elif kind == "grub" and "grub" in changed:
        firmware = firmware or ("uefi" if Path("/sys/firmware/efi").is_dir() else "bios")
        if firmware == "uefi":
            # The same two copies as finalization: the removable path and the NVRAM entry.
            run(["grub-install", "--target=x86_64-efi", "--efi-directory=/boot", "--bootloader-id=AGIOS", "--removable"])
            run(["grub-install", "--target=x86_64-efi", "--efi-directory=/boot", "--bootloader-id=AGIOS"])
        else:
            source = run(["findmnt", "-n", "-o", "SOURCE", "/boot"]).strip()
            disk = run(["lsblk", "-n", "-d", "-o", "PKNAME", source]).strip()
            if not disk:
                raise UpdateError("Could not find the GRUB bootloader disk")
            run(["grub-install", "--target=i386-pc", "/dev/" + disk])
        run(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
        done.append("grub")
    return done


def pacnew_files(etc=Path("/etc")):
    found = []
    for directory, _, files in os.walk(etc):
        found += [os.path.join(directory, name) for name in files if name.endswith((".pacnew", ".pacsave"))]
    return sorted(found)


def reboot_required(changed, modules=Path("/usr/lib/modules")):
    running = os.uname().release
    return bool(set(changed) & REBOOT_PACKAGES) or not (modules / running).is_dir()


def emit(text):
    print(text, flush=True)
    log(text)


def apply(force=False):
    require_root()
    handle = locked()
    try:
        if (PACMAN_DB / "db.lck").exists():
            if subprocess.run(["pgrep", "-x", "pacman"], capture_output=True).returncode == 0:
                raise UpdateError("The package manager is busy with another operation. Wait for it to finish and try again.")
            # The lock lives on disk and survives a reboot; removing it is the user's decision.
            raise UpdateError("An interrupted pacman operation left a lock (/var/lib/pacman/db.lck). "
                              "If no package manager is running now, remove it: "
                              "sudo rm /var/lib/pacman/db.lck — and try again.")
        low = on_battery_below()
        if low is not None and not force:
            raise UpdateError(f"Battery at {low}% and not charging. Plug in the power: losing power during "
                              "a kernel update can stop the computer from booting.")
        if free_bytes("/") < MIN_FREE:
            raise UpdateError("Less than 2 GiB free on the system partition. Free up space "
                              "(for example, sudo pacman -Sc) and try again.")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        status = read_status()
        status.pop("error", None)
        taken = None
        if root_filesystem() == "btrfs":
            emit("Taking a system snapshot before the update…")
            try:
                taken = snapshot(stamp)
                emit("Snapshot: " + taken)
            except UpdateError as exc:
                # For example an active swap file in the root subvolume; the update itself is still safe.
                emit("No snapshot taken, updating without one: " + str(exc).splitlines()[-1])
        before = installed_versions()
        emit("Updating the repository keys…")
        stream(["pacman", "-Sy", "--needed", "--noconfirm", "archlinux-keyring"])
        emit("Installing updates…")
        try:
            stream(["pacman", "-Su", "--noconfirm"])
        except UpdateError as exc:
            hint = ("Some packages may be updated already. Do not restart or install single "
                    "packages before you try again: sudo agi-os-update apply. If pacman asks a question "
                    "(a package conflict), run sudo pacman -Syu in a terminal and answer it")
            if taken:
                hint += f". System snapshot from before the update: {taken}"
            raise UpdateError(hint + "\n" + str(exc)) from None
        changed = changed_packages(before, installed_versions())
        emit(f"Packages updated: {len(changed)}")
        refreshed = refresh_bootloader(bootloader(), changed)
        if refreshed:
            emit("Bootloader updated: " + ", ".join(refreshed))
            if shutil.which("sbctl"):
                # Secure Boot: the freshly copied loader must be signed again before the next boot.
                run(["sbctl", "sign-all"])
                emit("Bootloader signed again (sbctl)")
        status.update({"checked_at": stamp, "updates": [], "kernel": False,
                       "reboot_required": reboot_required(changed), "applied_boot_id": boot_id(),
                       "pacnew": pacnew_files(),
                       "last_apply": {"at": stamp, "changed": changed, "snapshot": taken,
                                      "bootloader": refreshed, "result": "ok"}})
        write_status(status)
        if status["reboot_required"]:
            emit("Restart the computer to run the updated kernel and services.")
        if status["pacnew"]:
            emit("New versions of settings files are waiting to be compared (.pacnew): " + ", ".join(status["pacnew"]))
        emit("Update finished.")
        return status
    except UpdateError as exc:
        status = read_status()
        status["error"] = str(exc).splitlines()[0]
        status["last_apply"] = {"at": time.strftime("%Y%m%d-%H%M%S"), "result": "failed", "error": str(exc)[:2000]}
        try:
            write_status(status)
        except OSError:
            pass
        log("Update failed: " + str(exc))
        raise
    finally:
        handle.close()


def run_check():
    require_root()
    handle = locked()
    try:
        status = read_status()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        try:
            status.update(check(), checked_at=stamp)
            status.pop("error", None)
        except UpdateError as exc:
            status.update(error="Update check failed: " + str(exc).splitlines()[0], checked_at=stamp)
        # The reminder to reboot ends with the first boot after the update.
        if status.get("reboot_required") and status.get("applied_boot_id") != boot_id():
            status["reboot_required"] = False
        status["pacnew"] = pacnew_files()
        write_status(status)
        log(f"Check: {len(status.get('updates', []))} updates" + (", " + status["error"] if status.get("error") else ""))
        return status
    finally:
        handle.close()


def describe(status):
    if not status:
        return "Updates have not been checked yet. Check: sudo agi-os-update check"
    lines = [f"Last check: {status.get('checked_at', 'never')}"]
    if status.get("error"):
        lines.append(status["error"])
    updates = status.get("updates", [])
    lines.append(f"Updates available: {len(updates)}" + (" (including the kernel)" if status.get("kernel") else ""))
    lines += [f"  {u['name']} {u['old']} → {u['new']}" for u in updates[:200]]
    notice = notice_text({k: v for k, v in status.items() if k != "updates"})
    if notice:
        lines.append(notice.rstrip())
    return "\n".join(lines)


def should_notify(status, home=None, today=None):
    """At most one reminder a day, only when updates are pending."""
    if not status.get("updates") and not status.get("reboot_required"):
        return False
    marker = (home or Path.home()) / NOTIFY_STATE
    today = today or time.strftime("%Y-%m-%d")
    try:
        if marker.read_text().strip() == today:
            return False
    except OSError:
        pass
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(today)
    return True


def sudo_command(args):
    """sudo reads the password from stdin (-S) with no prompt text; -k never reuses a cached ticket."""
    return ["sudo", "-S", "-k", "-p", "", "--", "/usr/local/bin/agi-os-update", *args]


def gui():
    import threading
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk
    window = Gtk.Window(title="AGI OS — Updates")
    window.set_default_size(680, 520)
    window.set_border_width(20)
    window.connect("destroy", Gtk.main_quit)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    window.add(box)
    output = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
    scroll = Gtk.ScrolledWindow()
    scroll.add(output)
    box.pack_start(scroll, True, True, 0)
    password = Gtk.Entry(visibility=False, placeholder_text="Your password (the one for sudo)")
    box.pack_start(password, False, False, 0)
    row = Gtk.Box(spacing=10)
    check_button = Gtk.Button(label="Check now")
    apply_button = Gtk.Button(label="Update the system")
    apply_button.get_style_context().add_class("suggested-action")
    row.pack_end(apply_button, False, False, 0)
    row.pack_end(check_button, False, False, 0)
    box.pack_start(row, False, False, 0)
    buffer = output.get_buffer()
    buffer.set_text(describe(read_status()))

    def append(text):
        buffer.insert(buffer.get_end_iter(), text)
        output.scroll_to_iter(buffer.get_end_iter(), 0, False, 0, 0)

    def finished(code):
        for widget in (check_button, apply_button, password):
            widget.set_sensitive(True)
        append("\n" + ("Done." if code == 0 else "Not done: check the password and the messages above.") + "\n\n")
        append(describe(read_status()) + "\n")

    def start(args):
        secret = password.get_text()
        password.set_text("")
        if not secret:
            append("\nEnter your password to continue.\n")
            return
        for widget in (check_button, apply_button, password):
            widget.set_sensitive(False)
        buffer.set_text("")

        def work():
            proc = subprocess.Popen(sudo_command(args), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
            try:
                proc.stdin.write(secret + "\n")
                proc.stdin.close()
            except OSError:
                pass
            for line in proc.stdout:
                GLib.idle_add(append, line)
            GLib.idle_add(finished, proc.wait())

        threading.Thread(target=work, daemon=True).start()

    check_button.connect("clicked", lambda _: start(["check"]))
    apply_button.connect("clicked", lambda _: start(["apply", "--yes"]))
    # Enter in the password field is the window's main action: update.
    password.connect("activate", lambda _: start(["apply", "--yes"]))
    window.show_all()
    password.grab_focus()
    Gtk.main()


def target_files(session, kind):
    """Files the installer writes into the new system: (relative path, content, mode)."""
    files = [
        ("usr/local/share/agi-os/update.py", Path(__file__).read_text(), 0o644),
        ("usr/local/bin/agi-os-update", '#!/bin/sh\nexec python /usr/local/share/agi-os/update.py "$@"\n', 0o755),
        ("etc/systemd/system/agi-os-update-check.service",
         "[Unit]\nDescription=AGI OS: check for system updates\n"
         "Wants=network-online.target\nAfter=network-online.target\n\n"
         "[Service]\nType=oneshot\nExecStart=/usr/local/bin/agi-os-update check --quiet\n"
         "Nice=10\nIOSchedulingClass=idle\nProtectHome=read-only\nPrivateTmp=yes\n", 0o644),
        ("etc/systemd/system/" + TIMER,
         "[Unit]\nDescription=AGI OS: daily update check\n\n"
         "[Timer]\nOnBootSec=10min\nOnCalendar=daily\nRandomizedDelaySec=1h\nPersistent=true\n\n"
         "[Install]\nWantedBy=timers.target\n", 0o644),
        ("etc/profile.d/agi-os-update.sh",
         "# AGI OS: a one-line reminder about pending updates in interactive shells.\n"
         'case $- in *i*) [ -s /var/lib/agi-os/update-notice ] && cat /var/lib/agi-os/update-notice ;; esac\n', 0o644),
    ]
    if session:
        files += [
            ("etc/xdg/autostart/agi-os-update.desktop", "[Desktop Entry]\nType=Application\n"
             "Name=AGI OS — Update reminder\nExec=agi-os-update --gui --if-pending\nTerminal=false\n"
             "NoDisplay=true\n", 0o644),
            ("usr/share/applications/agi-os-update.desktop", "[Desktop Entry]\nType=Application\n"
             "Name=AGI OS — Updates\nComment=Check and install system updates\nExec=agi-os-update --gui\n"
             "Icon=system-software-update\nTerminal=false\nCategories=System;Settings;\n", 0o644),
        ]
    units = [TIMER] + (["systemd-boot-update.service"] if kind == "systemd-boot" else [])
    return files, units


def main(argv=None):
    parser = argparse.ArgumentParser(prog="agi-os-update", description="AGI OS system updates")
    parser.add_argument("action", nargs="?", choices=("status", "check", "apply"), default="status")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    parser.add_argument("--force", action="store_true", help="update even on a low battery")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--if-pending", action="store_true", help="with --gui: open only when updates wait, once a day")
    args = parser.parse_args(argv)
    try:
        if args.gui:
            if args.if_pending and not should_notify(read_status()):
                return 0
            gui()
            return 0
        if args.action == "check":
            status = run_check()
            if not args.quiet:
                print(describe(status))
            return 1 if status.get("error") else 0
        if args.action == "apply":
            require_root()
            if not args.yes:
                print(describe(read_status()))
                if input("Install all updates now? [y/N] ").strip().lower() not in ("y", "yes"):
                    return 1
            apply(force=args.force)
            return 0
        print(describe(read_status()))
        return 0
    except UpdateError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
