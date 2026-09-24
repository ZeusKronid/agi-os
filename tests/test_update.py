"""agi-os-update: the update tool the installer puts into the new system."""

import configparser
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
import update


def battery(root, name, kind="Battery", status="Discharging", capacity="20"):
    folder = root / name
    folder.mkdir()
    (folder / "type").write_text(kind + "\n")
    (folder / "status").write_text(status + "\n")
    (folder / "capacity").write_text(capacity + "\n")


class ParsingTests(unittest.TestCase):
    def test_pending_updates_skip_ignored_and_noise(self):
        text = ("linux 6.10.1.arch1-1 -> 6.10.2.arch1-1\nfirefox 130.0-1 -> 131.0-1\n"
                "grub 2:2.12-1 -> 2:2.12-2 [ignored]\nwarning: something\n")
        self.assertEqual(update.parse_updates(text), [
            {"name": "linux", "old": "6.10.1.arch1-1", "new": "6.10.2.arch1-1"},
            {"name": "firefox", "old": "130.0-1", "new": "131.0-1"}])

    def test_changed_packages_include_new_and_upgraded(self):
        self.assertEqual(update.changed_packages({"a": "1", "b": "1"}, {"a": "1", "b": "2", "c": "1"}), ["b", "c"])

    def test_reboot_after_kernel_or_missing_running_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            modules = Path(tmp)
            (modules / update.os.uname().release).mkdir()
            self.assertFalse(update.reboot_required(["firefox"], modules))
            self.assertTrue(update.reboot_required(["linux"], modules))
            self.assertTrue(update.reboot_required(["intel-ucode"], modules))
            (modules / update.os.uname().release).rmdir()
            self.assertTrue(update.reboot_required([], modules))

    def test_notice_lines(self):
        self.assertEqual(update.notice_text({"updates": []}), "")
        text = update.notice_text({"updates": [{"name": "linux"}], "kernel": True, "reboot_required": True,
                                   "pacnew": ["/etc/pacman.conf.pacnew"]})
        self.assertIn("updates available: 1 (including the kernel)", text)
        self.assertIn("sudo agi-os-update apply", text)
        self.assertIn("restart the computer", text)
        self.assertIn("/etc/pacman.conf.pacnew", text)

    def test_status_files_are_world_readable_and_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            update.write_status({"updates": [{"name": "a", "old": "1", "new": "2"}]}, state)
            self.assertEqual((state / "update-status.json").stat().st_mode & 0o777, 0o644)
            self.assertEqual((state / "update-notice").stat().st_mode & 0o777, 0o644)
            self.assertEqual(update.read_status(state / "update-status.json")["updates"][0]["name"], "a")
            self.assertEqual(sorted(p.name for p in state.iterdir()), ["update-notice", "update-status.json"])

    def test_pacnew_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            etc = Path(tmp)
            (etc / "pacman.d").mkdir()
            (etc / "pacman.d/mirrorlist.pacnew").write_text("")
            (etc / "fstab").write_text("")
            self.assertEqual(update.pacnew_files(etc), [str(etc / "pacman.d/mirrorlist.pacnew")])


class CheckTests(unittest.TestCase):
    def test_check_uses_a_private_sync_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, pacman_db = Path(tmp) / "db", Path(tmp) / "pacman"
            (pacman_db / "local").mkdir(parents=True)
            with patch.object(update, "run", return_value="") as run, \
                 patch.object(update.subprocess, "run", return_value=subprocess.CompletedProcess(
                     [], 0, "linux 1-1 -> 2-1\n", "")) as query:
                result = update.check(db, pacman_db)
            self.assertEqual(run.call_args.args[0], ["pacman", "-Sy", "--dbpath", str(db), "--logfile", "/dev/null"])
            self.assertEqual(query.call_args.args[0], ["pacman", "-Qu", "--dbpath", str(db)])
            self.assertEqual((db / "local").resolve(), (pacman_db / "local").resolve())
            self.assertTrue(result["kernel"])
            self.assertEqual(len(result["updates"]), 1)

    def test_nothing_pending_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            db, pacman_db = Path(tmp) / "db", Path(tmp) / "pacman"
            (pacman_db / "local").mkdir(parents=True)
            with patch.object(update, "run", return_value=""), \
                 patch.object(update.subprocess, "run", return_value=subprocess.CompletedProcess([], 1, "", "")):
                self.assertEqual(update.check(db, pacman_db), {"updates": [], "kernel": False})

    def test_a_real_local_directory_in_the_private_db_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "db"
            (db / "local").mkdir(parents=True)
            with patch.object(update, "run") as run:
                with self.assertRaises(update.UpdateError):
                    update.check(db, Path(tmp) / "pacman")
            run.assert_not_called()


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pacman = root / "pacman"
        self.pacman.mkdir()
        self.power = root / "power"
        self.power.mkdir()
        self.calls = []
        versions = iter([{"linux": "1", "grub": "1"}, {"linux": "2", "grub": "2"}])
        patches = [
            patch.object(update, "STATE", root / "state"), patch.object(update, "STATUS", root / "state/update-status.json"),
            patch.object(update, "LOCK", root / "lock"), patch.object(update, "LOG", root / "log/update.log"),
            patch.object(update, "PACMAN_DB", self.pacman), patch.object(update.os, "geteuid", return_value=0),
            patch.object(update, "free_bytes", return_value=10 * 1024 ** 3),
            patch.object(update, "root_filesystem", return_value="btrfs"),
            patch.object(update, "snapshot", side_effect=lambda stamp, **kw: self.calls.append(["snapshot"]) or "/.snapshots/x"),
            patch.object(update, "installed_versions", side_effect=lambda: next(versions)),
            patch.object(update, "stream", side_effect=lambda args: self.calls.append(args)),
            patch.object(update, "run", side_effect=lambda args, **kw: self.calls.append(args) or ""),
            patch.object(update, "bootloader", return_value="grub"),
            patch.object(update, "pacnew_files", return_value=[]),
            patch.object(update, "boot_id", return_value="boot-1"),
            patch.object(update.shutil, "which", return_value=None),
            patch.object(update.Path, "is_dir", lambda self: str(self) == "/sys/firmware/efi" or Path.exists(self)),
            patch("builtins.print"),
        ]
        original = update.on_battery_below
        patches.append(patch.object(update, "on_battery_below", lambda: original(supplies=self.power)))
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_snapshot_keyring_then_full_upgrade_then_bootloader(self):
        status = update.apply()
        order = [c[0] if c[0] != "pacman" else " ".join(c[:2]) for c in self.calls]
        self.assertEqual(order[:3], ["snapshot", "pacman -Sy", "pacman -Su"])
        self.assertIn("archlinux-keyring", self.calls[1])
        self.assertEqual(self.calls[2], ["pacman", "-Su", "--noconfirm"])
        self.assertIn("grub-install", order)
        self.assertEqual(order[-1], "grub-mkconfig")
        self.assertTrue(status["reboot_required"])
        self.assertEqual(status["last_apply"]["changed"], ["grub", "linux"])
        self.assertEqual(update.read_status()["updates"], [])

    def test_low_battery_is_refused_before_any_change(self):
        battery(self.power, "AC", kind="Mains", status="Unknown")
        battery(self.power, "BAT0", capacity="12")
        with self.assertRaises(update.UpdateError) as caught:
            update.apply()
        self.assertIn("12%", str(caught.exception))
        self.assertEqual(self.calls, [])
        self.assertEqual(update.read_status()["last_apply"]["result"], "failed")
        update.apply(force=True)
        self.assertTrue(self.calls)

    def test_charging_battery_is_fine(self):
        battery(self.power, "BAT0", status="Charging", capacity="5")
        update.apply()
        self.assertTrue(self.calls)

    def test_busy_package_manager_is_refused(self):
        (self.pacman / "db.lck").write_text("")
        for running, expected in ((0, "busy with another operation"), (1, "sudo rm /var/lib/pacman/db.lck")):
            with patch.object(update.subprocess, "run", return_value=subprocess.CompletedProcess([], running)):
                with self.assertRaises(update.UpdateError) as caught:
                    update.apply()
            self.assertIn(expected, str(caught.exception))
        self.assertTrue((self.pacman / "db.lck").exists())
        self.assertEqual(self.calls, [])

    def test_secure_boot_loader_is_signed_again(self):
        with patch.object(update.shutil, "which", return_value="/usr/bin/sbctl"):
            update.apply()
        self.assertEqual(self.calls[-1], ["sbctl", "sign-all"])

    def test_small_free_space_is_refused(self):
        with patch.object(update, "free_bytes", return_value=100 * 1024 ** 2):
            with self.assertRaises(update.UpdateError):
                update.apply()
        self.assertEqual(self.calls, [])

    def test_failed_upgrade_names_the_snapshot_and_is_recorded(self):
        def fail(args):
            self.calls.append(args)
            if args[:2] == ["pacman", "-Su"]:
                raise update.UpdateError("pacman failed (code 1)\nerror: failed to commit transaction")
        with patch.object(update, "stream", side_effect=fail):
            with self.assertRaises(update.UpdateError) as caught:
                update.apply()
        self.assertIn("/.snapshots/x", str(caught.exception))
        self.assertEqual(update.read_status()["last_apply"]["result"], "failed")

    def test_snapshot_failure_does_not_block_the_update(self):
        with patch.object(update, "snapshot", side_effect=update.UpdateError("ERROR: cannot snapshot: swapfile")):
            status = update.apply()
        self.assertIsNone(status["last_apply"]["snapshot"])
        self.assertIn(["pacman", "-Su", "--noconfirm"], self.calls)

    def test_non_root_is_refused(self):
        with patch.object(update.os, "geteuid", return_value=1000):
            with self.assertRaises(update.UpdateError):
                update.apply()
        self.assertEqual(self.calls, [])


class BootloaderTests(unittest.TestCase):
    def test_systemd_boot_is_updated_only_when_systemd_changed(self):
        with patch.object(update, "run", return_value="") as run:
            self.assertEqual(update.refresh_bootloader("systemd-boot", ["firefox"]), [])
            run.assert_not_called()
            self.assertEqual(update.refresh_bootloader("systemd-boot", ["systemd"]), ["systemd-boot"])
            run.assert_called_once_with(["bootctl", "--graceful", "update"])

    def test_bios_grub_goes_to_the_disk_holding_boot(self):
        answers = {"findmnt": "/dev/nvme0n1p2\n", "lsblk": "nvme0n1\n"}
        with patch.object(update, "run", side_effect=lambda args, **kw: answers.get(args[0], "")) as run:
            update.refresh_bootloader("grub", ["grub"], firmware="bios")
        commands = [c.args[0] for c in run.call_args_list]
        self.assertIn(["grub-install", "--target=i386-pc", "/dev/nvme0n1"], commands)
        self.assertEqual(commands[-1], ["grub-mkconfig", "-o", "/boot/grub/grub.cfg"])

    def test_uefi_grub_refreshes_both_copies(self):
        with patch.object(update, "run", return_value="") as run:
            update.refresh_bootloader("grub", ["grub"], firmware="uefi")
        installs = [c.args[0] for c in run.call_args_list if c.args[0][0] == "grub-install"]
        self.assertEqual(len(installs), 2)
        self.assertIn("--removable", installs[0])

    def test_bootloader_comes_from_the_installation_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "installation.json"
            record.write_text(json.dumps({"configuration": {"bootloader": "grub"}}))
            self.assertEqual(update.bootloader(record, Path(tmp)), "grub")
            (Path(tmp) / "loader").mkdir()
            (Path(tmp) / "loader/loader.conf").write_text("")
            self.assertEqual(update.bootloader(Path(tmp) / "missing.json", Path(tmp)), "systemd-boot")


class DesktopTests(unittest.TestCase):
    def test_reminder_at_most_once_a_day_and_only_when_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertFalse(update.should_notify({"updates": []}, home, "2026-09-23"))
            pending = {"updates": [{"name": "a"}]}
            self.assertTrue(update.should_notify(pending, home, "2026-09-23"))
            self.assertFalse(update.should_notify(pending, home, "2026-09-23"))
            self.assertTrue(update.should_notify(pending, home, "2026-09-24"))

    def test_password_goes_only_to_sudo_stdin(self):
        command = update.sudo_command(["apply", "--yes"])
        self.assertEqual(command[:6], ["sudo", "-S", "-k", "-p", "", "--"])
        self.assertEqual(command[6:], ["/usr/local/bin/agi-os-update", "apply", "--yes"])


class TargetFilesTests(unittest.TestCase):
    def test_console_system_gets_cli_timer_and_login_notice(self):
        files, units = update.target_files(False, "grub")
        paths = {path: (content, mode) for path, content, mode in files}
        self.assertEqual(paths["usr/local/share/agi-os/update.py"][0], (APP / "update.py").read_text())
        self.assertEqual(paths["usr/local/bin/agi-os-update"][1], 0o755)
        self.assertFalse(any(p.endswith(".desktop") for p in paths))
        self.assertEqual(units, ["agi-os-update-check.timer"])
        for path, (content, _) in paths.items():
            if path.startswith("etc/systemd/system/"):
                parser = configparser.ConfigParser(strict=True)
                parser.read_string(content)
                self.assertTrue(parser.has_section("Unit"), path)
        timer = configparser.ConfigParser()
        timer.read_string(paths["etc/systemd/system/agi-os-update-check.timer"][0])
        self.assertEqual(timer["Install"]["WantedBy"], "timers.target")
        self.assertEqual(timer["Timer"]["Persistent"], "true")
        script = paths["etc/profile.d/agi-os-update.sh"][0]
        self.assertEqual(subprocess.run(["sh", "-n"], input=script, text=True).returncode, 0)

    def test_desktop_system_gets_reminder_and_menu_entry(self):
        files, units = update.target_files(True, "systemd-boot")
        entries = {path: content for path, content, _ in files if path.endswith(".desktop")}
        self.assertEqual(len(entries), 2)
        for content in entries.values():
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(content)
            self.assertTrue(parser["Desktop Entry"]["Exec"].startswith("agi-os-update --gui"))
        self.assertIn("--if-pending", entries["etc/xdg/autostart/agi-os-update.desktop"])
        self.assertEqual(units, ["agi-os-update-check.timer", "systemd-boot-update.service"])

    def test_status_command_needs_no_root(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(update, "STATUS", Path(tmp) / "missing.json"), \
             patch("builtins.print") as printed:
            self.assertEqual(update.main(["status"]), 0)
        self.assertIn("not been checked yet", printed.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
