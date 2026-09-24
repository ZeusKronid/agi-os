"""Console keymap/font, fonts, locales, LC_* formats and time sync (CMP-122)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
import domain
import verify
from domain import Configuration, ValidationError
import test_installer
from test_installer import specification


def kbd_tree(root, keymaps=(), fonts=()):
    for name in keymaps:
        path = root / "keymaps/i386/qwerty" / (name + ".map.gz")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    for name in fonts:
        path = root / "consolefonts" / (name + ".psf.gz")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


class RegionalTestCase(unittest.TestCase):
    """Console files come from a temporary kbd tree, not from the host."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.kbd = Path(directory.name)
        kbd_tree(self.kbd, ("us", "de-latin1", "ruwin_alt_sh-UTF-8", "fr"), ("cyr-sun16", "eurlatgr", "ter-v32n"))
        patcher = patch.object(domain, "KBD", self.kbd)
        patcher.start()
        self.addCleanup(patcher.stop)

    def config(self, **changes):
        data = specification()
        data.update(changes)
        return Configuration.parse(data)


class DefaultsTests(RegionalTestCase):
    def test_russian_graphical_defaults(self):
        config = self.config(session="sway", locale="ru_RU.UTF-8", keyboard_layouts=["us", "ru"])
        self.assertEqual(config.effective_keymap(), "ruwin_alt_sh-UTF-8")
        self.assertEqual(config.effective_console_font(), "cyr-sun16")
        self.assertEqual(config.vconsole_conf(), "KEYMAP=ruwin_alt_sh-UTF-8\nFONT=cyr-sun16\n")
        self.assertEqual(config.effective_fonts(), ["ttf-dejavu", "ttf-liberation"])
        self.assertEqual(config.generated_locales(), ["en_US.UTF-8", "ru_RU.UTF-8"])
        self.assertEqual(config.locale_conf(), "LANG=ru_RU.UTF-8\n")
        self.assertTrue(config.settings_record()["cyrillic"])

    def test_cyrillic_layout_with_english_language_still_gets_cyrillic_console(self):
        config = self.config(locale="en_US.UTF-8", keyboard_layouts=["us", "ru"])
        self.assertEqual(config.effective_console_font(), "cyr-sun16")

    def test_english_console_system(self):
        config = self.config(session="", locale="en_US.UTF-8", keyboard_layouts=["us"])
        self.assertEqual(config.vconsole_conf(), "KEYMAP=us\nFONT=eurlatgr\n")
        self.assertEqual(config.effective_fonts(), [])
        self.assertEqual(config.generated_locales(), ["en_US.UTF-8"])

    def test_latin_primary_layout_becomes_console_keymap_when_it_exists(self):
        self.assertEqual(self.config(keyboard_layouts=["fr", "us"]).effective_keymap(), "fr")
        self.assertEqual(self.config(keyboard_layouts=["de", "us"]).effective_keymap(), "us")  # kbd calls it de-latin1
        self.assertEqual(self.config(keyboard_layouts=["us", "fr"]).effective_keymap(), "us")
        kbd_tree(self.kbd, ("uk",))
        self.assertEqual(self.config(keyboard_layouts=["gb"]).effective_keymap(), "uk")  # XKB gb is kbd uk

    def test_cjk_language_gets_cjk_fonts(self):
        config = self.config(session="sway", locale="ja_JP.UTF-8", keyboard_layouts=["us"])
        self.assertIn("noto-fonts-cjk", config.effective_fonts())


class ExplicitChoiceTests(RegionalTestCase):
    def test_explicit_console_and_fonts(self):
        config = self.config(console_keymap="de-latin1", console_font="ter-v32n",
                             fonts=["noto-fonts", "noto-fonts-emoji", "ttf-jetbrains-mono-nerd"])
        self.assertEqual(config.vconsole_conf(), "KEYMAP=de-latin1\nFONT=ter-v32n\n")
        # A Terminus console font needs its package; explicit fonts replace the defaults.
        self.assertEqual(config.effective_fonts(), ["noto-fonts", "noto-fonts-emoji", "ttf-jetbrains-mono-nerd", "terminus-font"])

    def test_formats_and_week_start(self):
        config = self.config(locale="en_US.UTF-8", locale_overrides=[
            {"variable": "LC_TIME", "locale": "en_GB.UTF-8"}, {"variable": "LC_MEASUREMENT", "locale": "ru_RU.UTF-8"},
            {"variable": "LC_COLLATE", "locale": "C.UTF-8"}])
        self.assertEqual(config.locale_conf(), "LANG=en_US.UTF-8\nLC_TIME=en_GB.UTF-8\n"
                         "LC_MEASUREMENT=ru_RU.UTF-8\nLC_COLLATE=C.UTF-8\n")
        # C.UTF-8 is built into glibc and never generated.
        self.assertEqual(config.generated_locales(), ["en_US.UTF-8", "en_GB.UTF-8", "ru_RU.UTF-8"])
        # Russian measurement units mean Russian text may appear in the console.
        self.assertEqual(config.effective_console_font(), "cyr-sun16")

    def test_roundtrip_and_digest(self):
        config = self.config(console_font="ter-v32n", fonts=["noto-fonts-emoji"], time_sync=False,
                             locale_overrides=[{"variable": "LC_TIME", "locale": "en_GB.UTF-8"}])
        again = Configuration.parse(json.loads(json.dumps(config.as_dict())))
        self.assertEqual(config, again)
        self.assertEqual(config.digest(), again.digest())
        self.assertNotEqual(config.digest(), self.config(console_font="ter-v32n", fonts=["noto-fonts-emoji"],
                            locale_overrides=[{"variable": "LC_TIME", "locale": "en_GB.UTF-8"}]).digest())

    def test_schema_lists_every_field_the_parser_requires(self):
        self.assertEqual(set(domain.CONFIG_SCHEMA["required"]), set(specification()) | set(domain.LATER_FIELDS))
        self.assertEqual(set(domain.CONFIG_SCHEMA["properties"]), set(Configuration.parse(specification()).as_dict()))

    def test_configuration_without_regional_fields_uses_automatic_choices(self):
        data = specification()
        for name in domain.LATER_FIELDS:
            data.pop(name, None)
        config = Configuration.parse(data)
        self.assertEqual((config.console_keymap, config.console_font, config.fonts, config.time_sync), ("", "", (), True))
        data["unknown"] = 1
        with self.assertRaises(ValidationError):
            Configuration.parse(data)

    def test_invalid_values_rejected(self):
        cases = [("console_keymap", "../../etc/passwd"), ("console_keymap", "no-such-map"),
                 ("console_font", "no-such-font"), ("console_font", "ter v32n"), ("console_keymap", None),
                 ("fonts", ["firefox"]), ("fonts", ["noto-fonts; reboot"]), ("fonts", ["fontconfig"]),
                 ("time_sync", "yes"), ("locale_overrides", {"LC_TIME": "en_GB.UTF-8"}),
                 ("locale_overrides", [{"variable": "LC_ALL", "locale": "en_GB.UTF-8"}]),
                 ("locale_overrides", [{"variable": "LANG", "locale": "en_GB.UTF-8"}]),
                 ("locale_overrides", [{"variable": "LC_TIME", "locale": "en_GB"}]),
                 ("locale_overrides", [{"variable": "LC_TIME", "locale": "en_GB.UTF-8\nLC_ALL=C"}]),
                 ("locale_overrides", [{"variable": "LC_TIME", "locale": "en_GB.UTF-8", "extra": 1}]),
                 ("locale_overrides", [{"variable": "LC_TIME", "locale": "en_GB.UTF-8"},
                                       {"variable": "LC_TIME", "locale": "ru_RU.UTF-8"}])]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValidationError):
                    self.config(**{field: value})

    def test_summary_shows_regional_settings(self):
        summary = self.config(locale_overrides=[{"variable": "LC_TIME", "locale": "en_GB.UTF-8"}], time_sync=False).summary(
            {"size": 64 * 2**30, "model": "disk"})
        self.assertIn("LC_TIME=en_GB.UTF-8", summary)
        self.assertIn("Time sync (NTP): off", summary)
        self.assertIn("Console: keymap ruwin_alt_sh-UTF-8 (automatic), font cyr-sun16 (automatic)", summary)


class WorkerRegionalTests(RegionalTestCase):
    def install(self, **changes):
        data = specification()
        data.update(changes)
        files = {}
        calls, events = test_installer.WorkerTests.fake_install(self, data=data, files=files)
        self.assertEqual(events[-1]["kind"], "installed", events[-1])
        return calls, {name: content.decode() for name, content in files.items()}

    def test_target_files_and_record(self):
        calls, files = self.install(session="", locale="ru_RU.UTF-8", keyboard_layouts=["us", "ru"],
                                    locale_overrides=[{"variable": "LC_TIME", "locale": "en_GB.UTF-8"}])
        self.assertEqual(files["etc/vconsole.conf"], "KEYMAP=ruwin_alt_sh-UTF-8\nFONT=cyr-sun16\n")
        self.assertEqual(files["etc/locale.conf"], "LANG=ru_RU.UTF-8\nLC_TIME=en_GB.UTF-8\n")
        self.assertEqual(files["etc/locale.gen"], "en_US.UTF-8 UTF-8\nru_RU.UTF-8 UTF-8\nen_GB.UTF-8 UTF-8\n")
        settings = json.loads(files["var/lib/agi-os/installation.json"])["settings"]
        self.assertEqual(settings["keymap"], "ruwin_alt_sh-UTF-8")
        self.assertIn(["arch-chroot", worker_target(calls), "systemctl", "enable", "systemd-timesyncd.service"], calls)
        # vconsole.conf exists before the initramfs is built, so the passphrase prompt uses it.
        self.assertLess(calls.index(["arch-chroot", worker_target(calls), "locale-gen"]),
                        calls.index(["arch-chroot", worker_target(calls), "mkinitcpio", "-P"]))

    def test_time_sync_declined(self):
        calls, _ = self.install(time_sync=False)
        target = worker_target(calls)
        self.assertNotIn(["arch-chroot", target, "systemctl", "enable", "systemd-timesyncd.service"], calls)
        self.assertIn(["arch-chroot", target, "systemctl", "disable", "systemd-timesyncd.service"], calls)

    def test_fonts_are_installed_with_the_base_system(self):
        calls, _ = self.install(fonts=["noto-fonts-emoji"], console_font="ter-v32n")
        pacstrap = next(c for c in calls if c[0] == "pacstrap")
        self.assertIn("noto-fonts-emoji", pacstrap)
        self.assertIn("terminus-font", pacstrap)

    def test_missing_console_file_in_target_fails_installation(self):
        import worker
        config = self.config()
        with tempfile.TemporaryDirectory() as tmp, patch.object(worker, "TARGET", Path(tmp)):
            with self.assertRaisesRegex(ValidationError, "no console keymap"):
                worker.check_console(config)


def worker_target(calls):
    return next(c[1] for c in calls if c[0] == "arch-chroot")


class VerifyRegionalTests(unittest.TestCase):
    def run_checks(self, vconsole, locale_conf, locales, fonts_lang="DejaVu Sans", timesync=0, graphical=True):
        settings = {"keymap": "ruwin_alt_sh-UTF-8", "console_font": "cyr-sun16", "fonts": ["ttf-dejavu"],
                    "locales": ["en_US.UTF-8", "ru_RU.UTF-8"], "locale_conf": ["LANG=ru_RU.UTF-8", "LC_TIME=en_GB.UTF-8"],
                    "time_sync": True, "cyrillic": True}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kbd_tree(root / "usr/share/kbd", ("ruwin_alt_sh-UTF-8",), ("cyr-sun16",))
            (root / "etc").mkdir()
            (root / "etc/vconsole.conf").write_text(vconsole)

            def command(args):
                if args[0] == "locale": return 0, locales
                if args[:2] == ["fc-list", ":lang=ru"]: return 0, fonts_lang
                if args[0] == "fc-list": return 0, "DejaVu Sans"
                if args[0] == "systemctl": return timesync, ""
                return 1, ""

            with patch.object(verify, "command", side_effect=command):
                return verify.regional_checks(settings, locale_conf, root, graphical)

    def test_all_pass(self):
        checks = self.run_checks("KEYMAP=ruwin_alt_sh-UTF-8\nFONT=cyr-sun16\n", ["LANG=ru_RU.UTF-8", "LC_TIME=en_GB.UTF-8"],
                                 "C\nC.utf8\nPOSIX\nen_US.utf8\nru_RU.utf8")
        self.assertTrue(all(checks.values()), checks)
        self.assertIn("Interface font with Cyrillic", checks)
        self.assertIn("Time sync (NTP)", checks)

    def test_each_regional_problem_is_reported(self):
        ok_console, ok_conf, ok_locales = "KEYMAP=ruwin_alt_sh-UTF-8\nFONT=cyr-sun16\n", ["LANG=ru_RU.UTF-8", "LC_TIME=en_GB.UTF-8"], "en_US.utf8\nru_RU.utf8"
        cases = [(("KEYMAP=us\nFONT=cyr-sun16\n", ok_conf, ok_locales), {}, "Console: keymap ruwin_alt_sh-UTF-8"),
                 (("KEYMAP=ruwin_alt_sh-UTF-8\n", ok_conf, ok_locales), {}, "Console: font cyr-sun16"),
                 ((ok_console, ["LANG=ru_RU.UTF-8"], ok_locales), {}, "Formats: LC_TIME=en_GB.UTF-8"),
                 ((ok_console, ok_conf, "en_US.utf8"), {}, "Locales generated: en_US.UTF-8, ru_RU.UTF-8"),
                 ((ok_console, ok_conf, ok_locales), {"fonts_lang": ""}, "Interface font with Cyrillic"),
                 ((ok_console, ok_conf, ok_locales), {"timesync": 1}, "Time sync (NTP)")]
        for args, kwargs, failing in cases:
            with self.subTest(failing=failing):
                checks = self.run_checks(*args, **kwargs)
                self.assertFalse(checks[failing])
                self.assertEqual([name for name, passed in checks.items() if not passed], [failing])

    def test_console_system_skips_gui_font_checks(self):
        checks = self.run_checks("KEYMAP=ruwin_alt_sh-UTF-8\nFONT=cyr-sun16\n", ["LANG=ru_RU.UTF-8", "LC_TIME=en_GB.UTF-8"],
                                 "en_US.utf8\nru_RU.utf8", graphical=False)
        self.assertNotIn("Interface fonts installed", checks)

    def test_locale_names_match_locale_a(self):
        self.assertEqual(verify.normalized_locale("ru_RU.UTF-8"), "ru_RU.utf8")
        self.assertEqual(verify.normalized_locale("C.UTF-8"), "C.utf8")

if __name__ == "__main__":
    unittest.main()
