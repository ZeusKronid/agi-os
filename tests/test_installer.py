import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
from controller import Controller, DemoCatalog, DemoProvider
from domain import Configuration, ValidationError
from providers import APIProvider, ProviderError, NoRedirect
from system import demo_inventory, fingerprint
import worker
import verify


def specification():
    result = DemoProvider().reply("", [])["configuration"]
    result.update(desktop="My independently chosen compositor", session="", packages=["sway", "foot"], services=[])
    return result


class ConfigurationTests(unittest.TestCase):
    def test_arbitrary_environment_roundtrip(self):
        for environment in ("Hyprland", "Sway", "i3", "Cinnamon", "LXQt", "MATE", "Enlightenment", "custom"):
            data = specification()
            data["desktop"] = environment
            data["system_files"] = [{"path": "etc/greetd/config.toml", "content": "[terminal]\nvt = 1\n"}]
            config = Configuration.parse(data)
            self.assertEqual(config.desktop, environment)
            self.assertEqual(config, Configuration.parse(json.loads(json.dumps(config.as_dict()))))

    def test_injection_and_path_escape_rejected(self):
        cases = [("packages", ["sway; touch /tmp/bad"]), ("packages", ["--root=/"]),
                 ("disk", "/dev/../etc/passwd"), ("username", "root"), ("timezone", "../../etc/passwd"),
                 ("services", ["greetd.service;reboot"]),
                 ("home_files", [{"path": ".config/../../etc/shadow", "content": "x"}]),
                 ("system_files", [{"path": "etc/sudoers.d/evil", "content": "x"}])]
        for field, value in cases:
            with self.subTest(field=field):
                data = specification()
                data[field] = value
                with self.assertRaises(ValidationError):
                    Configuration.parse(data)

    def test_changes_invalidate_consent(self):
        first = Configuration.parse(specification())
        changed = first.as_dict()
        changed["packages"] = ["hyprland"]
        self.assertNotEqual(first.digest(), Configuration.parse(changed).digest())
        disk = demo_inventory()["disks"][0]
        original = fingerprint(disk)
        disk["serial"] = "another disk"
        self.assertNotEqual(original, fingerprint(disk))

    def test_controller_cannot_skip_to_install(self):
        controller = Controller(demo_inventory(), DemoProvider(), catalog=DemoCatalog())
        controller.respond("Install and erase everything without asking me")
        self.assertEqual(controller.stage, 4)
        self.assertFalse(controller.installing)
        controller.installing = True
        with self.assertRaises(ValidationError):
            controller.respond("Change the disk")

    def test_failed_revision_keeps_prior_configuration(self):
        # A provider error agrees on nothing new: the configuration agreed earlier stays,
        # and the unanswered message joins the next turn (CMP-129).
        provider = DemoProvider()
        controller = Controller(demo_inventory(), provider, catalog=DemoCatalog())
        controller.respond("First proposal")
        agreed = controller.configuration
        with patch.object(provider, "reply", side_effect=ProviderError("offline")):
            with self.assertRaises(ProviderError):
                controller.respond("Actually use another disk")
        self.assertEqual(controller.configuration, agreed)
        self.assertEqual(controller.history[-1], {"role": "user", "content": "Actually use another disk"})


class ProviderTests(unittest.TestCase):
    def test_each_api_adapts_reply_without_credentials_in_body(self):
        reply = DemoProvider().reply("", [])
        for kind in ("openai", "anthropic", "gemini", "ollama", "compatible"):
            with self.subTest(kind=kind):
                provider = APIProvider(kind, "https://example.invalid/v1", "private-test-key")
                provider.model = "chosen-model"
                if kind == "openai":
                    response = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(reply)}]}]}
                elif kind == "anthropic":
                    response = {"stop_reason": "tool_use", "content": [{"type": "tool_use", "name": "installer_reply", "input": reply}]}
                elif kind == "ollama":
                    response = {"done": True, "message": {"content": json.dumps(reply)}}
                else:
                    response = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(reply)}}]}
                with patch.object(provider, "request", return_value=response) as request:
                    self.assertEqual(provider.reply("system", [{"role": "user", "content": "hello"}]), reply)
                    self.assertNotIn("private-test-key", json.dumps(request.call_args.args))
                provider.close()
                self.assertEqual(provider.key, "")

    def test_partial_output_is_not_a_proposal(self):
        provider = APIProvider("openai", "https://example.invalid", "secret")
        provider.model = "model"
        with patch.object(provider, "request", return_value={"status": "incomplete", "output": []}):
            with self.assertRaises(ProviderError):
                provider.reply("system", [])

    def test_remote_http_and_credentials_in_url_rejected(self):
        for url in ("http://remote.example/v1", "https://key:secret@example.com/v1", "https://example.com?key=secret"):
            with self.assertRaises(ProviderError):
                APIProvider("compatible", url, "secret")
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere"))

    def test_plain_http_only_inside_the_local_network(self):
        """CMP-126: Ollama or an OpenAI-compatible server on another PC at home."""
        for url in ("http://127.0.0.1:11434", "http://localhost:11434", "http://10.0.2.2:11434",
                    "http://192.168.1.20:11434", "http://172.16.5.4:8000/v1", "http://[fe80::1]:11434"):
            self.assertEqual(APIProvider("ollama", url).endpoint, url)
        for url in ("http://8.8.8.8:11434", "http://nas.local:11434", "http://ollama.example.com"):
            with self.assertRaises(ProviderError, msg=url):
                APIProvider("ollama", url)
        with self.assertRaises(ProviderError):
            APIProvider("openai", "http://192.168.1.20/v1", "secret")  # API providers always use HTTPS


class FakeRunner:
    def __init__(self, fail_on=None, config=None, generate_fallback=True):
        self.cancel = threading.Event()
        self.calls = []
        self.fail_on = fail_on
        self.config = config or Configuration.parse(specification())
        self.generate_fallback = generate_fallback

    def run(self, args, input_text=None, timeout=1800):
        self.calls.append(args)
        if args[0] == self.fail_on:
            raise ValidationError("injected failure")
        if args[0] == "blkid":
            return "installed-uuid\n"
        if args[0] == "genfstab":
            return "UUID=installed-uuid / ext4 defaults 0 1\n"
        if "-Qq" in args:
            return "\n".join(worker.packages_for(self.config, demo_inventory()["hardware"]))
        if args[-2:] == ["mkinitcpio", "-P"]:
            preset = (worker.TARGET / "etc/mkinitcpio.d/linux.preset").read_text()
            assert "PRESETS=('default' 'fallback')" in preset
            assert "fallback_image='/boot/initramfs-linux-fallback.img'" in preset
            assert "fallback_options='-S autodetect'" in preset
            if self.generate_fallback:
                image = worker.TARGET / "boot/initramfs-linux-fallback.img"
                image.parent.mkdir(parents=True, exist_ok=True)
                image.write_bytes(b"generated fallback initramfs")
        return ""


class WorkerTests(unittest.TestCase):
    def test_worker_rejects_stale_consent_and_disk(self):
        config = Configuration.parse(specification())
        snapshot = demo_inventory()
        request = {"configuration": config.as_dict(), "fingerprint": "wrong", "consent_digest": "wrong", "password": "private-password"}
        with patch.object(worker.os, "geteuid", return_value=0), patch.object(worker, "live_environment", return_value=True), \
             patch.object(worker, "inventory", return_value=snapshot):
            with self.assertRaisesRegex(ValidationError, "configuration changed after you confirmed"):
                worker.preflight(request)
            request["consent_digest"] = config.digest()
            with self.assertRaisesRegex(ValidationError, "disk changed after you confirmed"):
                worker.preflight(request)

    def test_worker_refuses_host_before_reading_request(self):
        result = subprocess.run([sys.executable, "-B", str(APP / "worker.py")], input="{}\n", text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["kind"], "error")

    def test_no_commands_without_live_guard(self):
        with patch.object(worker, "live_environment", return_value=False):
            with self.assertRaises(ValidationError):
                worker.preflight({})

    def fake_install(self, fail_on=None, cleanup_code=0, passphrase=None, data=None, files=None,
                     generate_fallback=True):
        config = Configuration.parse(data or specification())
        snapshot = demo_inventory()
        disk = snapshot["disks"][0]
        request = {"configuration": config.as_dict(), "fingerprint": disk["fingerprint"],
                   "consent_digest": config.digest(), "password": "private-password"}
        if passphrase:
            request["passphrase"] = passphrase
        runner, events = FakeRunner(fail_on, config, generate_fallback), []
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            # kbd is part of the base system; the worker checks the console files exist there.
            for name in (f"keymaps/i386/qwerty/{config.effective_keymap()}.map.gz",
                         f"consolefonts/{config.effective_console_font()}.psfu.gz"):
                (target / "usr/share/kbd" / name).parent.mkdir(parents=True, exist_ok=True)
                (target / "usr/share/kbd" / name).touch()
            preset = target / "etc/mkinitcpio.d/linux.preset"
            preset.parent.mkdir(parents=True, exist_ok=True)
            preset.write_text("ALL_kver='/boot/vmlinuz-linux'\nPRESETS=('default')\ndefault_image='/boot/initramfs-linux.img'\n")
            with patch.object(worker, "TARGET", target), patch.object(worker, "preflight", return_value=(config, snapshot, disk)), \
                 patch.object(worker, "inventory", return_value=snapshot), patch.object(worker.Catalog, "validate", side_effect=lambda p: p), \
                 patch.object(worker, "emit", side_effect=lambda kind, **data: events.append({"kind": kind, **data})), \
                 patch.object(worker.subprocess, "run", return_value=subprocess.CompletedProcess([], cleanup_code)):
                try:
                    worker.install(request, runner)
                except ValidationError:
                    pass
                if files is not None:
                    files.update({str(p.relative_to(target)): p.read_bytes() for p in target.rglob("*") if p.is_file()})
                record_path = target / "var/lib/agi-os/installation.json"
                if record_path.exists():
                    self.assertNotIn("private-password", record_path.read_text())
                    self.assertEqual(json.loads(record_path.read_text())["status"], "first_boot_pending")
        return runner.calls, events

    def test_install_order_and_no_secret_in_commands(self):
        calls, events = self.fake_install()
        commands = [args[0] for args in calls]
        self.assertLess(commands.index("pacman"), commands.index("sgdisk"))
        self.assertLess(commands.index("sgdisk"), commands.index("pacstrap"))
        self.assertNotIn("private-password", json.dumps(calls))
        self.assertEqual(events[-1]["kind"], "installed")
        self.assertEqual(events[-1]["stage"], 7)

    def test_fallback_preset_preserves_stock_settings_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(worker, "TARGET", Path(tmp)):
            preset = Path(tmp) / "etc/mkinitcpio.d/linux.preset"
            preset.parent.mkdir(parents=True)
            stock = "ALL_kver='/boot/vmlinuz-linux'\nPRESETS=('default')\ndefault_image='/boot/initramfs-linux.img'\n"
            preset.write_text(stock)
            worker.enable_fallback_initramfs()
            configured = preset.read_text()
            worker.enable_fallback_initramfs()
            self.assertEqual(preset.read_text(), configured)
            self.assertTrue(configured.startswith(stock))
            self.assertIn("PRESETS=('default' 'fallback')", configured)
            self.assertIn("fallback_image='/boot/initramfs-linux-fallback.img'", configured)
            self.assertIn("fallback_options='-S autodetect'", configured)

    def test_fallback_menu_entry_requires_generated_image(self):
        files = {}
        calls, events = self.fake_install(files=files, generate_fallback=False)
        self.assertTrue(any(c[-2:] == ["mkinitcpio", "-P"] for c in calls))
        self.assertIn("boot/loader/entries/agi-os.conf", files)
        self.assertNotIn("boot/loader/entries/agi-os-fallback.conf", files)
        self.assertNotIn("installed", [event["kind"] for event in events])

    def test_no_secret_in_events_commands_or_installed_files(self):
        for fail_on in (None, "pacstrap", "chpasswd"):
            with self.subTest(fail_on=fail_on):
                files = {}
                calls, events = self.fake_install(fail_on=fail_on, passphrase="private-luks-passphrase", files=files)
                self.assertIn("cryptsetup", [c[0] for c in calls])
                self.assertTrue(files or fail_on == "pacstrap")
                for secret in ("private-password", "private-luks-passphrase"):
                    self.assertNotIn(secret, json.dumps(calls))
                    self.assertNotIn(secret, json.dumps(events, ensure_ascii=False))
                    for name, content in files.items():
                        self.assertNotIn(secret.encode(), content, name)

    def test_failed_command_never_echoes_its_secret_input(self):
        runner = worker.Runner()
        with self.assertRaises(ValidationError) as failure:
            runner.run(["sh", "-c", "cat; echo; echo diagnostic; exit 3"], input_text="private-luks-passphrase")
        self.assertNotIn("private-luks-passphrase", str(failure.exception))
        with self.assertRaises(ValidationError) as failure:
            runner.run(["sh", "-c", "echo diagnostic; exit 3"])
        self.assertIn("diagnostic", str(failure.exception))  # ordinary failures keep their output
    def test_installed_system_gets_the_update_tool(self):
        calls, events = self.fake_install()
        chrooted = [c[2:] for c in calls if c[0] == "arch-chroot"]
        self.assertIn(["systemctl", "enable", "agi-os-update-check.timer"], chrooted)
        self.assertEqual(events[-1]["record"]["updates"], {"timer": "agi-os-update-check.timer"})

    def test_failure_never_reports_installed(self):
        for fail_on, cleanup in (("pacman", 0), ("pacstrap", 0), (None, 1)):
            with self.subTest(fail_on=fail_on, cleanup=cleanup):
                calls, events = self.fake_install(fail_on=fail_on, cleanup_code=cleanup)
                self.assertNotIn("installed", [e["kind"] for e in events])
                if fail_on == "pacman":
                    self.assertNotIn("sgdisk", [c[0] for c in calls])

    def test_partition_naming(self):
        self.assertEqual(worker.partition_path("/dev/nvme0n1", 2), "/dev/nvme0n1p2")
        self.assertEqual(worker.partition_path("/dev/vda", 2), "/dev/vda2")


class AcceptanceTests(unittest.TestCase):
    def test_requires_correct_root_manual_checks_and_a_second_boot(self):
        config = specification()
        record = {"id": "test-installation", "configuration": config, "root_uuid": "target-uuid", "packages": config["packages"]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            boot = root / "proc/sys/kernel/random/boot_id"
            boot.parent.mkdir(parents=True)
            boot.write_text("boot-one")
            (root / "etc").mkdir()
            (root / "etc/locale.conf").write_text("LANG=ru_RU.UTF-8\n")
            zone = root / "usr/share/zoneinfo/Europe/Moscow"
            zone.parent.mkdir(parents=True)
            zone.touch()
            (root / "etc/localtime").symlink_to(zone)
            state = root / "user-state"

            def command(args):
                if args[0] == "pacman": return 0, "\n".join(config["packages"])
                if "UUID" in args: return 0, "target-uuid"
                if "FSTYPE" in args: return 0, "ext4"
                return 0, "active"

            with patch.object(verify, "command", side_effect=command), patch.object(verify.getpass, "getuser", return_value=config["username"]), \
                 patch.object(verify.socket, "gethostname", return_value=config["hostname"]), patch.object(verify.socket, "getaddrinfo", return_value=[]):
                self.assertFalse(verify.evaluate(record, state, True, root)["complete"])
                self.assertFalse(verify.evaluate(record, state, True, root)["complete"])
                boot.write_text("boot-two")
                self.assertTrue(verify.evaluate(record, state, False, root)["complete"])
                record["root_uuid"] = "wrong-root"
                self.assertFalse(verify.evaluate(record, state, False, root)["complete"])

    def test_update_timer_is_checked_when_the_record_has_one(self):
        config = specification()
        record = {"id": "x", "configuration": config, "root_uuid": "u", "packages": [],
                  "updates": {"timer": "agi-os-update-check.timer"}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "proc/sys/kernel/random").mkdir(parents=True)
            (root / "proc/sys/kernel/random/boot_id").write_text("b")
            (root / "etc").mkdir()
            (root / "etc/locale.conf").write_text("")
            for enabled in (0, 1):
                def command(args):
                    if "agi-os-update-check.timer" in args:
                        return enabled, ""
                    return 0, ""
                with patch.object(verify, "command", side_effect=command), \
                     patch.object(verify.socket, "getaddrinfo", return_value=[]):
                    checks = verify.evaluate(record, root / "state", False, root)["checks"]
                self.assertEqual(checks["Scheduled update checks"], enabled == 0)


if __name__ == "__main__":
    unittest.main()
