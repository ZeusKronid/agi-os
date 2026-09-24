"""The Live website, the Live image and the installed system's tools speak English (CMP-150).

The engine used to write Russian messages that a translation table turned into English for the
native installer. The website is the only interface now, so the messages are English at the
source: no Cyrillic may remain in the Live image, the website or the engine, and the texts the
engine builds at run time (hardware, drivers, file checks, login review, summary) are English.
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(ENGINE))
import configcheck
import hardware
from controller import DemoProvider
from domain import Configuration, DEFAULT_SYSTEM, ValidationError

CYRILLIC = re.compile("[Ѐ-ԯ]")
BINARY = {".ttf", ".otf", ".png", ".jpg", ".svg", ".ico", ".woff", ".woff2", ".pyc"}
# The native GTK installer and its translation table leave with CMP-147.
LEAVING = {ENGINE / "app.py"}


def shipped():
    """Every text file of the Live image (engine, services, desktop files) and of the website."""
    for base in (ROOT / "archiso", ROOT / "web"):
        for path in sorted(base.rglob("*")):
            if path.is_file() and path.suffix not in BINARY and path not in LEAVING and "tests" not in path.relative_to(ROOT).parts:
                yield path


class NoCyrillicShippedTest(unittest.TestCase):
    def test_live_image_and_website_have_no_cyrillic(self):
        found = []
        for path in shipped():
            for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                if CYRILLIC.search(line):
                    found.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:100]}")
        self.assertEqual(found, [], "\n".join(found))

    def test_the_scan_covers_the_engine_and_the_website(self):
        names = {path.name for path in shipped()}
        for name in ("domain.py", "worker.py", "hardware.py", "configcheck.py", "verify.py", "update.py",
                     "server.py", "storage_worker.py", "finalize_worker.py", "preview_record.py", "diagnostics.py",
                     "release.py", "app.js", "index.html"):
            self.assertIn(name, names)


def device(klass, vendor, vendor_id, device_id, name, driver="", bus="pci", kind=None):
    entry = {"class": klass, "vendor": vendor, "vendor_id": vendor_id, "device_id": device_id, "name": name,
             "driver": driver, "bus": bus}
    return {**entry, "kind": kind} if kind else entry


def computer(**changes):
    data = {"cpu": {"vendor": "Intel", "model": "Core i7"}, "memory": 16 * 2**30, "virtualization": "none",
            "chassis": {"type": "Notebook", "vendor": "Lenovo", "product": "T14", "portable": True, "battery": True},
            "gpus": [device("0300", "Intel", "8086", "a788", "UHD Graphics", "i915"),
                     device("0300", "NVIDIA", "10de", "2717", "RTX 4090 Laptop"),
                     device("0300", "NVIDIA", "10de", "1c8d", "GTX 1050 Mobile")],
            "network": [device("0280", "Broadcom", "14e4", "43a0", "BCM4360", kind="wifi"),
                        device("0280", "MediaTek", "14c3", "0616", "MT7922", kind="wifi"),
                        device("0200", "Realtek", "10ec", "8125", "RTL8125", "r8169", kind="ethernet")],
            "audio": [device("0401", "Intel", "8086", "7a50", "HD Audio", "snd_hda_intel")],
            "bluetooth": [device("e0", "Intel", "8087", "0033", "AX211 Bluetooth", bus="usb")],
            "usb": [device("0e", "Chicony", "04f2", "b6dd", "Integrated Camera", bus="usb")],
            "tpm": True, "secure_boot": True, "setup_mode": True}
    return hardware.profile({**data, **changes})


class RunTimeTextsTest(unittest.TestCase):
    def assertEnglish(self, value, context=""):
        text = repr(value)
        self.assertIsNone(CYRILLIC.search(text), f"{context}: {text[:400]}")

    def test_hardware_lines_and_driver_plans(self):
        cases = {
            "laptop": computer(),
            "virtual": computer(virtualization="kvm", gpus=[device("0300", "QEMU", "1234", "1111", "Virtual VGA")],
                                chassis={"portable": False, "battery": False}, secure_boot=False, setup_mode=None),
            "undetected": computer(detected=False, gpus=[], network=[], audio=[], bluetooth=[], secure_boot=None),
            "empty": hardware.profile({}),
        }
        choices = [((), "xfce"), (("nvidia-open",), "sway"), (("linux-zen",), "hyprland"), (("linux-lts",), "xfce"), ((), "")]
        for name, profile in cases.items():
            self.assertEnglish(hardware.describe(profile), name)
            for packages, session in choices:
                self.assertEnglish(hardware.driver_plan(profile, packages, session), f"{name} {packages} {session}")
        self.assertEnglish(hardware.demo(), "demo")
        with self.assertRaises(ValueError) as caught:
            hardware.profile(None)
        self.assertEnglish(str(caught.exception))

    def test_file_check_errors_and_labels(self):
        broken = {
            ".config/app/settings.json": "{", ".config/Code/User/settings.json": "{/* x", ".config/app/x.toml": "a = ",
            ".config/app/x.xml": "<a>", ".config/autostart/x.desktop": "Name=x", ".config/app/x.py": "def (",
            ".config/systemd/user/x.service": "ExecStart=/bin/true", ".config/sway/config": "bar {",
            ".config/hypr/hyprland.conf": "}", ".config/foot/foot.ini": "no equals", ".config/app/x.ini": "k=v",
            ".config/app/y.ini": "[a\nk", ".config/autostart/y.desktop": "[Desktop Entry]\nType=Application\nName=y",
            ".config/autostart/z.desktop": "[Desktop Entry]\nType=Application\n",
        }
        for path, content in broken.items():
            self.assertEnglish(configcheck.summary("home", path), path)
            try:
                configcheck.static("home", path, content)
            except configcheck.ConfigCheckError as exc:
                self.assertEnglish(str(exc), path)
        for path, content in {"etc/X11/xorg.conf.d/10-x.conf": 'Section "Device"\n', "etc/X11/xorg.conf.d/20-x.conf": "EndSection\n",
                              "etc/systemd/system/x.service": "[Unit]\nx"}.items():
            self.assertEnglish(configcheck.summary("system", path), path)
            try:
                configcheck.static("system", path, content)
            except configcheck.ConfigCheckError as exc:
                self.assertEnglish(str(exc), path)
        self.assertEnglish(configcheck.HINTS)
        self.assertEnglish(configcheck.FORMATS)

    def test_summary_login_review_and_default_system(self):
        data = DemoProvider().reply("", [])["configuration"]
        data.update(swap="hibernate", home_files=[
            {"path": ".config/autostart/sync.desktop", "content": "[Desktop Entry]\nType=Application\nName=Sync\nExec=syncthing\n"},
            {"path": ".config/hypr/hyprland.conf", "content": "exec-once = waybar\n"},
            {"path": ".config/fish/config.fish", "content": "echo hi\n"},
            {"path": ".config/systemd/user/x.service", "content": "[Service]\nExecStart=/usr/bin/true\n"}])
        config = Configuration.parse(data)
        self.assertEnglish(config.login_entries(), "login entries")
        disk = {"path": "/dev/vda", "size": 64 * 2**30, "model": None, "serial": None, "tran": "nvme", "rota": False}
        for profile in (computer(), None):
            self.assertEnglish(config.summary(disk, profile), "summary")
        self.assertEnglish(Configuration.parse({**data, "swap": "zram"}).summary(disk, computer()), "zram summary")
        self.assertEnglish(DEFAULT_SYSTEM, "default system")
        self.assertEnglish(DemoProvider().reply("", []), "demo reply")

    def test_validation_errors(self):
        data = DemoProvider().reply("", [])["configuration"]
        broken = [{**data, "locale": "xx"}, {**data, "timezone": "Mars/Base"}, {**data, "username": "root"},
                  {**data, "swap": "disk"}, {**data, "swap": "hibernate", "filesystem": "f2fs"}, {**data, "services": ["debug-shell.service"]},
                  {**data, "console_keymap": "nope"}, {**data, "fonts": ["firefox"]}, {**data, "locale_overrides": [["LC_ALL", "C.UTF-8"]]},
                  {**data, "home_files": [{"path": "../x", "content": ""}]}, {**data, "system_files": [{"path": "etc/sudoers", "content": ""}]},
                  {k: v for k, v in data.items() if k != "hostname"}, "not a configuration"]
        for value in broken:
            with self.assertRaises(ValidationError) as caught:
                Configuration.parse(value)
            self.assertEnglish(str(caught.exception), repr(value)[:80])


if __name__ == "__main__":
    unittest.main()
