"""CMP-133: the model cannot write code that runs as root or in every process, and
whatever runs at login is listed separately for an explicit review."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
from controller import DemoProvider
from domain import Configuration, ValidationError, system_path_allowed
import worker


def config_with(home=(), system=()):
    data = DemoProvider().reply("", [])["configuration"]
    data.update(home_files=[{"path": p, "content": c} for p, c in home],
                system_files=[{"path": p, "content": c} for p, c in system])
    return Configuration.parse(data)


class ProtectedPathTests(unittest.TestCase):
    def test_root_and_every_process_paths_rejected(self):
        for path in ("etc/ld.so.preload", "etc/ld.so.conf.d/evil.conf", "etc/xdg/autostart/x.desktop",
                     "etc/systemd/user/x.service", "etc/systemd/user-generators/x",
                     "etc/systemd/system.conf.d/env.conf", "etc/profile.d/x.sh", "etc/profile",
                     "etc/bash.bashrc", "etc/zsh/zshenv", "etc/security/pam_env.conf", "etc/pam.d/login",
                     "etc/sudoers.d/x", "etc/doas.conf", "etc/tmpfiles.d/x.conf", "etc/cron.d/x",
                     "etc/NetworkManager/dispatcher.d/10-x", "etc/X11/xinit/xinitrc.d/50-x.sh",
                     "etc/pacman.d/hooks/x.hook", "etc/default/grub", "etc/systemd/zram-generator.conf",
                     "usr/local/share/agi-os/verify.py", "usr/local/share/dbus-1/services/x.service",
                     "etc//profile.d/./x.sh", "etc/systemd/system/getty@.service.d/x.conf"):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                config_with(system=[(path, "x")])

    def test_ordinary_configuration_still_allowed(self):
        allowed = [("etc/greetd/config.toml", '[default_session]\ncommand = "tuigreet --cmd sway"\n'),
                   ("etc/environment", "QT_QPA_PLATFORMTHEME=qt5ct\nMOZ_ENABLE_WAYLAND=1\n"),
                   ("etc/sysctl.d/99-swappiness.conf", "vm.swappiness=10\n"),
                   ("etc/udev/rules.d/60-io.rules", 'ACTION=="add", ATTR{queue/scheduler}="bfq"\n'),
                   ("etc/modprobe.d/audio.conf", "options snd_hda_intel power_save=1\n"),
                   ("etc/lightdm/lightdm-gtk-greeter.conf", "[greeter]\ntheme-name=Adwaita-dark\n"),
                   ("etc/systemd/logind.conf.d/lid.conf", "[Login]\nHandleLidSwitch=suspend\n"),
                   ("etc/X11/xorg.conf.d/30-touchpad.conf", 'Section "InputClass"\nEndSection\n'),
                   ("etc/xdg/xfce4/helpers.rc", "TerminalEmulator=xfce4-terminal\n"),
                   ("etc/sddm.conf.d/theme.conf", "[Theme]\nCurrent=breeze\n[Users]\nMaximumUid=60000\n")]
        config = config_with(home=[(".config/environment.d/qt.conf", "QT_SCALE_FACTOR=1.5\n")], system=allowed)
        self.assertEqual(len(config.system_files), len(allowed))

    def test_dangerous_content_in_allowed_files_rejected(self):
        cases = [("etc/environment", "LD_PRELOAD=/usr/local/share/x.so\n"),
                 ("etc/environment.d/10.conf", "export BASH_ENV=/tmp/x\n"),
                 ("etc/udev/rules.d/99-x.rules", 'ACTION=="add", RUN+="/bin/sh -c id"\n'),
                 ("etc/udev/rules.d/99-y.rules", 'IMPORT{program}="/bin/x"\n'),
                 ("etc/udev/rules.d/99-z.rules", 'ENV{SYSTEMD_WANTS}+="debug-shell.service"\n'),
                 ("etc/modprobe.d/x.conf", "install usb_storage /bin/sh -c id\n"),
                 ("etc/lightdm/lightdm.conf", "[Seat:*]\ndisplay-setup-script=/bin/sh -c id\n"),
                 ("etc/lightdm/lightdm.conf.d/50.conf", "[Seat:*]\nsession-wrapper=/tmp/x\n"),
                 ("etc/sysctl.d/50.conf", "kernel.core_pattern=|/bin/sh -c id\n"),
                 ("etc/greetd/config.toml", '[initial_session]\ncommand = "sway"\nuser = "u"\n'),
                 ("etc/lightdm/lightdm.conf.d/60.conf", "[Seat:*]\nautologin-user=u\n"),
                 ("etc/sddm.conf.d/autologin.conf", "[Autologin]\nSession=plasma\nUser=u\n"),
                 ("etc/gdm/custom.conf", "[daemon]\nAutomaticLoginEnable=True\n")]
        for path, content in cases:
            with self.subTest(path=path), self.assertRaises(ValidationError):
                config_with(system=[(path, content)])
        with self.assertRaises(ValidationError):
            config_with(home=[(".config/environment.d/x.conf", "LD_LIBRARY_PATH=/tmp\n")])

    def test_root_shell_services_rejected(self):
        data = DemoProvider().reply("", [])["configuration"]
        data["services"] = ["debug-shell.service"]
        with self.assertRaises(ValidationError):
            Configuration.parse(data)

    def test_symlink_in_target_cannot_redirect_a_system_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "etc/sudoers.d").mkdir(parents=True)
            os.symlink("sudoers.d", target / "etc/innocent")
            with patch.object(worker, "TARGET", target):
                self.assertTrue(system_path_allowed("etc/innocent/x"))
                self.assertEqual(worker.resolved("etc/innocent/x"), "etc/sudoers.d/x")
                self.assertFalse(system_path_allowed(worker.resolved("etc/innocent/x")))
                os.symlink("/etc", target / "etc/outside")
                with self.assertRaises(ValidationError):
                    worker.resolved("etc/outside/passwd")


class LoginReviewTests(unittest.TestCase):
    def test_login_entries_list_exact_commands(self):
        config = config_with(
            home=[(".config/autostart/sync.desktop", "[Desktop Entry]\nType=Application\nExec=syncthing serve\n"),
                  (".config/sway/config", "set $mod Mod4\nexec waybar\nexec_always kanshi\nbindsym $mod+Return exec foot\n"),
                  (".config/hypr/hyprland.conf", "monitor=,preferred,auto,1\nexec-once = mako\n"),
                  (".config/systemd/user/x.service", "[Service]\nExecStart=/usr/bin/x --daemon\n"),
                  (".config/labwc/autostart", "# comment\nswaybg -i bg.png &\n"),
                  (".config/foot/foot.ini", "[main]\nfont=monospace:size=11\n")],
            system=[("etc/greetd/config.toml", '[default_session]\ncommand = "tuigreet --cmd sway"\n')])
        entries = {e["path"]: e["commands"] for e in config.login_entries()}
        self.assertEqual(entries["~/.config/autostart/sync.desktop"], ["Exec=syncthing serve"])
        self.assertEqual(entries["~/.config/sway/config"], ["exec waybar", "exec_always kanshi"])
        self.assertEqual(entries["~/.config/hypr/hyprland.conf"], ["exec-once = mako"])
        self.assertEqual(entries["~/.config/systemd/user/x.service"], ["ExecStart=/usr/bin/x --daemon"])
        self.assertEqual(entries["~/.config/labwc/autostart"], ["swaybg -i bg.png &"])
        self.assertEqual(entries["/etc/greetd/config.toml"], ['command = "tuigreet --cmd sway"'])
        self.assertNotIn("~/.config/foot/foot.ini", entries)
        summary = config.summary({"size": 2**34})
        self.assertIn("ЗАПУСКАЕТСЯ ПРИ ВХОДЕ", summary)
        self.assertIn("syncthing serve", summary)

    def test_lua_hyprland_start_hooks_and_scripts_are_listed(self):
        lua = ('hl.bind("SUPER + Return", hl.dsp.exec_cmd("foot"))\n'
               'hl.on("hyprland.start", function ()\n    hl.exec_cmd("waybar")\nend)\n')
        config = config_with(home=[(".config/hypr/hyprland.lua", lua),
                                   (".config/hypr/welcome.sh", "# greet\nprintf 'hi'\nexec /bin/bash -i\n")])
        entries = {e["path"]: e["commands"] for e in config.login_entries()}
        self.assertEqual(entries["~/.config/hypr/hyprland.lua"], ['hl.exec_cmd("waybar")'])
        self.assertEqual(entries["~/.config/hypr/welcome.sh"], ["printf 'hi'", "exec /bin/bash -i"])

    def test_plain_configuration_needs_no_login_review(self):
        config = config_with(home=[(".config/hypr/hyprland.conf", "monitor=,preferred,auto,1\n")])
        self.assertEqual(config.login_entries(), [])
        self.assertNotIn("ЗАПУСКАЕТСЯ ПРИ ВХОДЕ", config.summary({"size": 2**34}))


if __name__ == "__main__":
    unittest.main()
