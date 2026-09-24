"""The AGIOS standard system for users who do not want to choose (CMP-99)."""

import json
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
import worker
from controller import Controller, DemoCatalog, DemoProvider
from domain import DEFAULT_SYSTEM, Configuration, default_configuration, default_system_context
from system import demo_inventory


class DefaultSystemTests(unittest.TestCase):
    def test_valid_for_each_firmware(self):
        for firmware, loader in (("uefi", "systemd-boot"), ("bios", "grub")):
            with self.subTest(firmware=firmware):
                config = default_configuration(firmware, "/dev/vda", "alice", locale="ru_RU.UTF-8",
                                               timezone="Europe/Moscow", keyboard_layouts=("us", "ru"))
                self.assertEqual(config.bootloader, loader)
                self.assertEqual(config.session, "xfce")
                self.assertEqual(config, Configuration.parse(json.loads(json.dumps(config.as_dict()))))

    def test_complete_desktop(self):
        config = default_configuration("uefi", "/dev/vda", "alice")
        packages = set(worker.packages_for(config, demo_inventory()["hardware"]))
        # Session, greeter, terminal, file manager, browser, network and volume applets.
        for package in ("xfce4-session", "lightdm", "lightdm-gtk-greeter", "xfce4-terminal", "thunar", "firefox",
                        "network-manager-applet", "xfce4-pulseaudio-plugin", "xorg-server", "ttf-dejavu"):
            self.assertIn(package, packages)
        self.assertEqual(config.services, ("lightdm.service",))
        self.assertIn("user-session=xfce", dict(config.system_files)["etc/lightdm/lightdm.conf.d/50-agios-default.conf"])
        self.assertTrue(config.requirements)

    def test_context_for_the_model_is_the_preset_with_this_firmware_loader(self):
        self.assertEqual(default_system_context("bios"), {**DEFAULT_SYSTEM, "bootloader": "grub"})
        # Personal choices are never preset.
        for personal in ("disk", "username", "hostname", "locale", "timezone", "keyboard_layouts"):
            self.assertNotIn(personal, DEFAULT_SYSTEM)

    def test_model_sees_the_preset_and_a_proposal_from_it_is_accepted(self):
        seen = []

        class ChoosingProvider(DemoProvider):
            def reply(self, system, messages):
                seen.append(system)
                data = system.split("AGIOS standard system (data, default_system): ", 1)[1]
                proposal = json.loads(data.split("\nDetected hardware (data): ", 1)[0])
                proposal.update(disk="/dev/vda", hostname="agios", username="alice", locale="ru_RU.UTF-8",
                                timezone="Europe/Moscow", keyboard_layouts=["us", "ru"])
                return {"message": "Стандартная система AGIOS", "suggestions": [], "lookup": [], "configuration": proposal}

        controller = Controller(demo_inventory(), ChoosingProvider(), catalog=DemoCatalog())
        controller.respond("Не хочу ничего выбирать — поставь стандартную систему")
        self.assertEqual(controller.stage, 4)
        self.assertEqual(controller.configuration.packages, tuple(DEFAULT_SYSTEM["packages"]))
        self.assertIn("If the user does not want to choose", seen[0])

    def test_welcome_page_offers_it(self):
        page = (Path(__file__).resolve().parents[1] / "web/static/index.html").read_text()
        self.assertIn("Choose for me", page)


if __name__ == "__main__":
    unittest.main()
