"""Static checks of the Live image profile: no Codex/GTK-era entry points remain."""

import configparser
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "archiso"
AIROOTFS = PROFILE / "airootfs"
APP = AIROOTFS / "usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
from chatgpt import ChatGPTProvider


def text_files():
    for path in AIROOTFS.rglob("*"):
        if path.is_file() and not path.is_symlink():
            try:
                yield path, path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue


def packages():
    lines = (PROFILE / "packages.x86_64").read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


class LiveImageTests(unittest.TestCase):
    def test_no_full_access_agent_configuration(self):
        for path, content in text_files():
            self.assertNotIn("danger-full-access", content, path)
        self.assertEqual([p for p in AIROOTFS.rglob(".codex")], [])

    def test_no_terminal_agent_instructions(self):
        self.assertEqual([p for p in AIROOTFS.rglob("AGENTS.md")], [])

    def test_desktop_entries_do_not_start_codex(self):
        entries = list(AIROOTFS.rglob("*.desktop"))
        self.assertTrue(entries)
        for path in entries:
            parser = configparser.ConfigParser(interpolation=None)
            parser.read(path, encoding="utf-8")
            command = parser["Desktop Entry"].get("Exec", "")
            self.assertNotIn("codex", command.lower(), path)
            self.assertNotIn("xfce4-terminal", command, path)

    def test_local_commands_do_not_start_codex(self):
        for path in (AIROOTFS / "usr/local/bin").iterdir():
            self.assertNotIn("codex", path.read_text().lower(), path)

    def test_gtk_installer_is_gone(self):
        # CMP-147: the website is the only Live interface; the native GTK installer was removed.
        self.assertFalse((APP / "app.py").exists())
        self.assertFalse((ROOT / "scripts/run-native-installer.sh").exists())
        self.assertFalse((ROOT / "tests/gui_smoke.py").exists())
        self.assertFalse((AIROOTFS / "usr/local/share/agi-os/welcome.html").exists())
        self.assertFalse({"python-gobject", "python-cairo"} & packages())
        launcher = (AIROOTFS / "usr/local/bin/agi-installer").read_text()
        self.assertIn("http://localhost:8787", launcher)
        self.assertNotIn("app.py", launcher)

    def test_website_keeps_the_sunrise_fonts(self):
        # The native installer is gone, but the website still serves these fonts.
        fonts = AIROOTFS / "usr/share/fonts/agios"
        for name in ("Geist.ttf", "GeistMono.ttf", "Newsreader.ttf", "Newsreader-Italic.ttf"):
            self.assertTrue((fonts / name).is_file(), name)

    def test_chatgpt_backend_packages_remain(self):
        self.assertTrue({"openai-codex", "bubblewrap"} <= packages())

    def test_ntfs_resize_tools_are_in_live(self):
        # Arch split the FUSE driver from the userspace tools. The storage helper
        # needs ntfsresize to offer and perform a data-preserving NTFS shrink.
        self.assertIn("ntfsprogs", packages())


class BootMediaTests(unittest.TestCase):
    def test_boot_cd_does_not_get_a_failing_loop_unit(self):
        # CMP-148: systemd-loop@<cd>.service for the hybrid ISO failed and left the Live "degraded".
        rule = AIROOTFS / "etc/udev/rules.d/98-agi-no-cdrom-loop.rules"
        self.assertLess(rule.name, "99-systemd.rules")
        lines = [line for line in rule.read_text().splitlines() if line and not line.startswith("#")]
        self.assertEqual(len(lines), 1)
        self.assertIn('ENV{ID_CDROM}=="1"', lines[0])
        self.assertTrue(lines[0].endswith('ENV{ID_PART_GPT_AUTO_ROOT_DISK_NEEDS_LOOP}=""'))


class CopyToRamTests(unittest.TestCase):
    def test_boot_entries_keep_the_boot_medium_mounted(self):
        # archiso's copytoram=auto copies the image into memory on a USB stick and unmounts it;
        # the website, the preview VM and the install all run from /run/archiso/bootmnt.
        entries = [PROFILE / "efiboot/loader/entries/01-archiso-linux.conf", PROFILE / "syslinux/archiso_sys-linux.cfg"]
        for path in entries:
            lines = [line for line in path.read_text().splitlines() if line.split()[:1] in (["options"], ["APPEND"])]
            self.assertEqual(len(lines), 1, path)
            self.assertIn("copytoram=n", lines[0].split(), path)

    def test_preview_guest_does_not_copy_itself_into_memory(self):
        runtime = (ROOT / "web/runtime.py").read_text()
        options = re.search(r"^GUEST_OPTIONS = '([^']*)'", runtime, re.M).group(1)
        self.assertIn("copytoram=n", options.split())

    def test_smoke_boot_uses_a_usb_stick(self):
        smoke = (ROOT / "scripts/ci/smoke-boot.py").read_text()
        self.assertIn("usb-storage,drive=live", smoke)
        self.assertNotIn("ide-cd,drive=live", smoke)


class FirefoxPolicyTests(unittest.TestCase):
    def test_live_browser_neither_saves_passwords_nor_opens_extra_tabs(self):
        # The website asks for the new system's passwords: the Live Firefox must not offer to
        # save or generate them, and no privacy-notice tab should open next to the website.
        policies = json.loads((AIROOTFS / "usr/lib/firefox/distribution/policies.json").read_text())["policies"]
        self.assertIs(policies["PasswordManagerEnabled"], False)
        self.assertIs(policies["OfferToSaveLogins"], False)
        self.assertIs(policies["DisableTelemetry"], True)
        self.assertEqual(policies["OverrideFirstRunPage"], "")
        self.assertIs(policies["Preferences"]["signon.generation.enabled"]["Value"], False)


class WebsiteLayoutTests(unittest.TestCase):
    def test_found_previews_stay_in_one_column(self):
        # Sunrise E2E: .notice is a flex column with max-height; with flex-wrap: wrap the list of
        # found previews moved into a second column past the right edge and its buttons vanished.
        css = (ROOT / "web/static/style.css").read_text()
        rules = [line for line in css.splitlines() if line.startswith(".notice {")]
        self.assertIn("flex-wrap: nowrap", rules[-1])
        self.assertIn("#orphanList { display: block; }", css)


class HeliosDesktopTests(unittest.TestCase):
    XFCONF = AIROOTFS / "home/agi/.config/xfce4/xfconf/xfce-perchannel-xml"

    def channel(self, name):
        return ElementTree.parse(self.XFCONF / f"{name}.xml").getroot()

    def test_panel_launchers_and_icons_exist(self):
        panel = self.channel("xfce4-panel")
        plugins = panel.find("property[@name='plugins']")
        launchers = [p for p in plugins if p.get("value") == "launcher"]
        self.assertEqual(len(launchers), 3)
        for plugin in launchers:
            number = plugin.get("name").removeprefix("plugin-")
            for item in plugin.find("property[@name='items']"):
                path = AIROOTFS / f"home/agi/.config/xfce4/panel/launcher-{number}" / item.get("value")
                self.assertTrue(path.is_file(), path)
        for prop in panel.iter("property"):
            if prop.get("name") == "button-icon":
                self.assertTrue((AIROOTFS / prop.get("value").lstrip("/")).is_file())

    def test_window_theme_has_every_image_for_its_buttons(self):
        general = self.channel("xfwm4").find("property[@name='general']")
        settings = {p.get("name"): p.get("value") for p in general}
        theme = AIROOTFS / "usr/share/themes" / settings["theme"] / "xfwm4"
        self.assertTrue((theme / "themerc").is_file())
        buttons = {"H": "hide", "M": "maximize", "C": "close"}
        names = [buttons[key] for key in settings["button_layout"] if key in buttons]
        names += ["maximize-toggled", "top-left", "top-right", "left", "right", "bottom"]
        names += [f"title-{n}" for n in range(1, 6)]
        for name in names:
            states = ("active", "inactive") if not name.startswith(tuple(buttons.values())) \
                else ("active", "inactive", "prelight", "pressed")
            for state in states:
                self.assertTrue((theme / f"{name}-{state}.png").is_file(), f"{name}-{state}")

    def test_installer_window_and_wallpaper_share_the_horizon(self):
        # agi-desktop stands the installer window on the wallpaper's horizon: both need the same numbers.
        render = (ROOT / "scripts/live-desktop/render.py").read_text()
        helper = (AIROOTFS / "usr/local/bin/agi-desktop").read_text()
        width, height = re.search(r"^WIDTH, HEIGHT = (\d+), (\d+)", render, re.M).groups()
        horizon = re.search(r"^HORIZON = ([\d.]+)", render, re.M).group(1)
        self.assertIn(f"image_width={width} image_height={height} horizon={horizon}", helper)
        wallpaper = re.search(r"^wallpaper=(\S+)", helper, re.M).group(1)
        self.assertTrue((AIROOTFS / wallpaper.lstrip("/")).is_file())
        self.assertIn('["/usr/local/bin/agi-desktop"]="0:0:755"', (PROFILE / "profiledef.sh").read_text())
        self.assertIn("agi-desktop place", (AIROOTFS / "usr/local/bin/agi-installer").read_text())
        self.assertTrue({"wmctrl", "xfce4-notifyd"} <= packages())

    def test_every_monitor_falls_back_to_the_horizon(self):
        # xfdesktop keys wallpapers by connector name and shows its compiled-in default
        # (xfce-x.svg in xfdesktop 4.20) on any monitor without a setting: the build replaces it.
        hook = (AIROOTFS / "etc/pacman.d/hooks/agios-default-wallpaper.hook").read_text()
        self.assertTrue(hook.startswith("# remove from airootfs!"))
        self.assertIn("Target = usr/share/backgrounds/xfce/xfce-x.svg", hook)
        source = re.search(r"^Exec = /usr/bin/cp -f (\S+) /usr/share/backgrounds/xfce/xfce-x.svg$", hook, re.M).group(1)
        self.assertTrue((AIROOTFS / source.lstrip("/")).is_file())

    def test_every_channel_is_valid_xml(self):
        for path in self.XFCONF.glob("*.xml"):
            self.assertEqual(ElementTree.parse(path).getroot().get("name"), path.stem, path)


class ChatGPTIsolationTests(unittest.TestCase):
    def test_backend_runs_in_bubblewrap_without_host_home_or_tools(self):
        proc = MagicMock()
        proc.stdout = iter(())
        proc.poll.return_value = None
        with patch("chatgpt.shutil.which", return_value="/usr/bin/tool"), \
             patch("chatgpt.subprocess.Popen", return_value=proc) as popen, \
             patch.object(ChatGPTProvider, "rpc", return_value={}), \
             patch.object(ChatGPTProvider, "send"):
            provider = ChatGPTProvider()
            provider.owner.join(timeout=5)
        args = popen.call_args.args[0]
        self.assertEqual(args[0], "bwrap")
        self.assertIn("--unshare-all", args)
        home = str(Path.home())
        # The home is a new empty directory, never a bind of the Live user's home.
        self.assertEqual(args[args.index("--dir") + 1], home)
        for flag in ("--bind", "--ro-bind"):
            for index, value in enumerate(args):
                if value == flag:
                    self.assertFalse(args[index + 1].startswith(home), args[index + 1])
        codex = args[args.index("codex"):]
        self.assertIn("features.shell_tool=false", codex)
        self.assertIn('cli_auth_credentials_store="ephemeral"', codex)
        self.assertEqual(codex[-3:], ["app-server", "--listen", "stdio://"])
        self.assertEqual(set(popen.call_args.kwargs["env"]) - {"PATH", "HOME", "LANG"}, set())


if __name__ == "__main__":
    unittest.main()
