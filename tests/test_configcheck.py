import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
import configcheck
from configcheck import ConfigCheckError, static, tool_checks
from controller import Controller, DemoCatalog, DemoProvider
from domain import Configuration, ValidationError
from system import demo_inventory
import worker

VALID = {
    ("home", ".config/waybar/config"): '{\n  // top bar\n  "layer": "top", /* inline */\n  "modules-left": ["sway/workspaces",],\n  "format": "{} // not a comment",\n}\n',
    ("home", ".config/waybar/style.jsonc"): '{"a": 1}',
    ("home", ".config/foot/foot.ini"): "font=monospace:size=11\n\n[colors]\nalpha=0.9\n# comment\n",
    ("home", ".config/sway/config"): 'set $mod Mod4\ninput * {\n  xkb_layout "us,ru"\n}\nbindsym $mod+Return exec foot "{"\n',
    ("home", ".config/i3/config"): "set $mod Mod4\nbar {\n status_command i3status\n}\n",
    ("home", ".config/hypr/hyprland.conf"): "input { # keyboard {\n  kb_layout = us,ru\n}\n# }\n",
    ("home", ".config/alacritty/alacritty.toml"): '[font]\nsize = 11\n',
    ("home", ".config/xfce4/xfconf/xfce-perchannel-xml/keyboard-layout.xml"):
        '<?xml version="1.0" encoding="UTF-8"?>\n<channel name="keyboard-layout" version="1.0"><property name="Default" type="empty"/></channel>\n',
    ("home", ".config/autostart/nm-applet.desktop"): "[Desktop Entry]\nType=Application\nName=Network\nName[ru]=Сеть\nExec=nm-applet %U\n",
    ("home", ".config/qtile/config.py"): "keys = []\n",
    ("home", ".config/systemd/user/sync.service"): "[Unit]\nDescription=Sync\n[Service]\nExecStart=/usr/bin/true \\\n  --flag\n",
    ("system", "etc/systemd/logind.conf.d/lid.conf"): "[Login]\nHandleLidSwitch=suspend\n",
    ("system", "etc/X11/xorg.conf.d/30-touchpad.conf"): 'Section "InputClass"\n  Identifier "touchpad"\n  Driver "libinput"\nEndSection\n',
    ("system", "etc/lightdm/lightdm-gtk-greeter.conf"): "[greeter]\ntheme-name = Adwaita-dark\n",
    ("system", "etc/greetd/config.toml"): '[terminal]\nvt = 1\n[default_session]\ncommand = "tuigreet --cmd sway"\n',
    ("system", "etc/xdg/foot/foot.ini"): "[main]\nfont=monospace:size=11\n",
    ("home", ".config/kitty/kitty.conf"): "anything goes here: no checker { [ \n",
}

INVALID = {
    ("home", ".config/waybar/config"): ('{"layer": "top" "height": 30}', "строка 1"),
    ("home", ".config/waybar/style.jsonc"): ('{"a": 1 /* never closed', "незакрытый комментарий"),
    ("home", ".config/app/settings.json"): ("{'single': 'quotes'}", "JSON"),
    ("home", ".config/foot/foot.ini"): ("[main\nfont=x\n", "секции"),
    ("home", ".config/hypr/hyprland.conf"): ("input {\n  kb_layout = us\n", "не закрыт блок"),
    ("home", ".config/sway/config"): ("}\n", "лишняя закрывающая"),
    ("home", ".config/alacritty/alacritty.toml"): ("[font\nsize = 11\n", "TOML"),
    ("home", ".config/xfce4/xfconf/xfce-perchannel-xml/x.xml"): ("<channel><property></channel>", "XML"),
    ("home", ".config/autostart/app.desktop"): ("[Desktop Entry]\nType=Application\nName=App\n", "Exec"),
    ("home", ".config/autostart/other.desktop"): ("[Something]\nName=x\n", "Desktop Entry"),
    ("home", ".config/qtile/config.py"): ("def broken(:\n", "Python"),
    ("system", "etc/systemd/logind.conf.d/lid.conf"): ("HandleLidSwitch=suspend\n", "вне секции"),
    ("system", "etc/X11/xorg.conf.d/30-touchpad.conf"): ('Section "InputClass"\n  Identifier "t"\n', "EndSection"),
    ("system", "etc/lightdm/lightdm.conf"): ("[Seat:*]\nthis line has no value\n", "ключ=значение"),
}


class StaticCheckTests(unittest.TestCase):
    def test_valid_files_pass(self):
        for (scope, path), content in VALID.items():
            with self.subTest(path=path):
                static(scope, path, content)

    def test_invalid_files_are_explained_with_their_path(self):
        for (scope, path), (content, reason) in INVALID.items():
            with self.subTest(path=path):
                with self.assertRaises(ConfigCheckError) as caught:
                    static(scope, path, content)
                message = str(caught.exception)
                self.assertIn(("~/" if scope == "home" else "/") + path, message)
                self.assertIn(reason, message)

    def test_jsonc_keeps_strings_and_line_numbers(self):
        text = '{\n/* a\nb */ "url": "http://x//y", // c\n"n": [1,2,],\n}'
        self.assertEqual(json.loads(configcheck.strip_jsonc(text)), {"url": "http://x//y", "n": [1, 2]})

    def test_configuration_rejects_invalid_file(self):
        data = DemoProvider().reply("", [])["configuration"]
        data["home_files"] = [{"path": ".config/waybar/config", "content": '{"layer": }'}]
        with self.assertRaisesRegex(ValidationError, "waybar/config"):
            Configuration.parse(data)

    def test_model_receives_the_error_and_fixes_the_file(self):
        good = DemoProvider().reply("", [])
        bad = json.loads(json.dumps(good))
        bad["configuration"]["home_files"] = [{"path": ".config/foot/foot.ini", "content": "[main\n"}]
        good["configuration"]["home_files"] = [{"path": ".config/foot/foot.ini", "content": "[main]\nfont=monospace\n"}]
        provider = DemoProvider()
        replies = iter([bad, good])
        with patch.object(provider, "reply", side_effect=lambda system, history: next(replies)):
            controller = Controller(demo_inventory(), provider, catalog=DemoCatalog())
            controller.respond("Sway with foot")
        self.assertEqual(controller.configuration.home_files[0][1], "[main]\nfont=monospace\n")
        rejected = [m["content"] for m in controller.history if "Application validation rejected" in m["content"]]
        self.assertTrue(rejected and "~/.config/foot/foot.ini" in rejected[0])

    def test_review_lists_the_checks(self):
        self.assertEqual(configcheck.summary("home", ".config/foot/foot.ini"), ["INI", "foot"])
        self.assertEqual(configcheck.summary("home", ".config/kitty/kitty.conf"), [])
        self.assertIn("Hyprland", configcheck.summary("home", ".config/hypr/hyprland.conf"))


class FeedbackTests(unittest.TestCase):
    def test_check_failure_joins_the_next_user_turn(self):
        controller = Controller(demo_inventory(), DemoProvider(), catalog=DemoCatalog())
        controller.respond("first")
        controller.report_check_failure("foot: invalid section name")
        seen = []
        with patch.object(controller.provider, "reply", side_effect=lambda system, history: seen.append(list(history)) or DemoProvider().reply("", [])):
            controller.respond("please fix")
        roles = [m["role"] for m in seen[0]]
        self.assertTrue(all(a != b for a, b in zip(roles, roles[1:])), roles)
        self.assertIn("invalid section name", seen[0][-1]["content"])
        self.assertIn("please fix", seen[0][-1]["content"])


class Runner:
    def __init__(self, fail=None):
        self.cancel = threading.Event()
        self.calls, self.fail = [], fail

    def run(self, args, input_text=None, timeout=1800):
        self.calls.append(args)
        if self.fail and self.fail in args:
            raise ValidationError(f"Ошибка arch-chroot (код 230)\nerr: config.c:3283: foot.ini:1: [colors]: invalid section name: colors")
        return ""


class ToolCheckTests(unittest.TestCase):
    def config(self, **files):
        data = DemoProvider().reply("", [])["configuration"]
        data.update(files)
        return Configuration.parse(data)

    def run_checks(self, config, binaries, fail=None, layouts=None):
        runner = Runner(fail)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for binary in binaries:
                (target / binary).parent.mkdir(parents=True, exist_ok=True)
                (target / binary).touch()
            (target / "var/tmp").mkdir(parents=True)
            if layouts is not None:
                (target / "usr/share/X11/xkb/symbols").mkdir(parents=True)
                for layout in layouts:
                    (target / "usr/share/X11/xkb/symbols" / layout).touch()
            with patch.object(worker, "TARGET", target):
                try:
                    worker.check_generated_files(config, runner)
                    error = None
                except ValidationError as exc:
                    error = str(exc)
                leftover = (target / "var/tmp/agi-os-config-check").exists()
        return runner.calls, error, leftover

    def test_program_checks_run_as_the_user_and_report_failure(self):
        config = self.config(home_files=[{"path": ".config/foot/foot.ini", "content": "[colors]\nx=1\n"},
                                         {"path": ".config/hypr/hyprland.conf", "content": "monitor=,preferred,auto,1\n"}])
        calls, error, leftover = self.run_checks(config, ["usr/bin/foot", "usr/bin/Hyprland"], fail="/usr/bin/foot")
        foot = next(c for c in calls if "/usr/bin/foot" in c)
        self.assertEqual(foot[:6], ["arch-chroot", foot[1], "runuser", "-u", "tester", "--"])
        self.assertIn("/home/tester/.config/foot/foot.ini", foot)
        self.assertIn("XDG_RUNTIME_DIR=/var/tmp/agi-os-config-check", foot)
        self.assertTrue(any("/usr/bin/Hyprland" in c and "--verify-config" in c for c in calls))
        self.assertTrue(error.startswith(worker.CONFIG_CHECK_FAILED))
        self.assertIn("~/.config/foot/foot.ini — foot", error)
        self.assertIn("invalid section name", error)
        self.assertNotIn("Hyprland", error)
        self.assertFalse(leftover)

    def test_missing_program_is_skipped_and_system_files_run_as_root(self):
        config = self.config(home_files=[{"path": ".config/sway/config", "content": "set $mod Mod4\n"}],
                             system_files=[{"path": "etc/profile.d/agi.sh", "content": "export A=1\n"}])
        calls, error, _ = self.run_checks(config, ["usr/bin/bash"])
        self.assertIsNone(error)
        self.assertFalse(any("/usr/bin/sway" in c for c in calls))
        bash = next(c for c in calls if "/usr/bin/bash" in c)
        self.assertEqual(bash, ["arch-chroot", bash[1], "/usr/bin/bash", "-n", "/etc/profile.d/agi.sh"])

    def test_unknown_keyboard_layout_blocks_the_preview(self):
        config = self.config()
        _, error, _ = self.run_checks(config, [], layouts=["us"])
        self.assertIn("«ru»", error)
        _, error, _ = self.run_checks(config, [], layouts=["us", "ru"])
        self.assertIsNone(error)

    def test_tool_selection_by_path(self):
        self.assertEqual(tool_checks("home", ".config/kitty/kitty.conf"), [])
        self.assertEqual(tool_checks("system", "etc/systemd/logind.conf.d/x.conf"), [])
        self.assertEqual(tool_checks("system", "etc/systemd/user/x.service")[0][0], "systemd-analyze")


if __name__ == "__main__":
    unittest.main()
