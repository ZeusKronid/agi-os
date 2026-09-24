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
from controller import DemoProvider
from domain import GIB, Configuration, ValidationError, hibernation_swap_size
from hardware import initramfs_config
from system import demo_inventory
import verify
import worker

EXT4_FILEFRAG = """Filesystem type is: ef53
File size of /mnt/agi-os/swap/swapfile is 17179869184 (4194304 blocks of 4096 bytes)
 ext:     logical_offset:        physical_offset: length:   expected: flags:
   0:        0..   30719:    1605632..   1636351:  30720:             unwritten
   1:    30720..   63487:    1638400..   1671167:  32768:    1636352: unwritten
/mnt/agi-os/swap/swapfile: 2 extents found
"""


def specification(**changes):
    data = DemoProvider().reply("", [])["configuration"]
    data.update(changes)
    return data


class ConfigurationTests(unittest.TestCase):
    def test_missing_swap_keeps_zram_and_hibernate_is_a_distinct_choice(self):
        data = specification()
        del data["swap"]
        old = Configuration.parse(data)
        self.assertEqual(old.swap, "zram")
        self.assertEqual(old, Configuration.parse(old.as_dict()))
        hibernating = Configuration.parse(specification(swap="hibernate"))
        self.assertNotEqual(old.digest(), hibernating.digest())
        self.assertIn("swap file /swap/swapfile (16 GiB, the size of RAM) inside the root", hibernating.summary({"size": 64 * GIB}, demo_inventory()["hardware"]))

    def test_unknown_mode_and_f2fs_hibernation_rejected(self):
        for changes in ({"swap": "partition"}, {"swap": "hibernate", "filesystem": "f2fs"}, {"swap": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                Configuration.parse(specification(**changes))
        for filesystem in ("ext4", "btrfs", "xfs"):
            Configuration.parse(specification(swap="hibernate", filesystem=filesystem))

    def test_swap_size_is_ram_rounded_up(self):
        self.assertEqual(hibernation_swap_size(int(15.3 * GIB)), 16 * GIB)
        self.assertEqual(hibernation_swap_size(8 * GIB), 8 * GIB)
        for memory in (0, None, -1, "16"):
            with self.subTest(memory=memory), self.assertRaises(ValidationError):
                hibernation_swap_size(memory)


class InitramfsTests(unittest.TestCase):
    def test_resume_after_encrypt_and_before_filesystems(self):
        hooks = initramfs_config({}, True, True).split("HOOKS=(")[1].split(")")[0].split()
        self.assertLess(hooks.index("encrypt"), hooks.index("resume"))
        self.assertLess(hooks.index("resume"), hooks.index("filesystems"))
        self.assertIn("resume", initramfs_config({}, False, True))
        self.assertEqual(initramfs_config({}, False), "")
        self.assertNotIn("resume", initramfs_config({}, True))


class SwapRunner:
    def __init__(self, outputs):
        self.cancel = threading.Event()
        self.calls, self.outputs = [], outputs

    def run(self, args, input_text=None, timeout=1800):
        self.calls.append(args)
        for key, value in self.outputs.items():
            if key in args:
                return value
        return ""


class SwapFileTests(unittest.TestCase):
    def test_filefrag_offset_in_pages(self):
        self.assertEqual(worker.first_extent_offset(EXT4_FILEFRAG), 1605632)
        small = EXT4_FILEFRAG.replace("blocks of 4096", "blocks of 1024")
        self.assertEqual(worker.first_extent_offset(small), 1605632 // 4)
        with self.assertRaises(ValidationError):
            worker.first_extent_offset("File size of x is 0 (0 blocks of 4096 bytes)\nx: 0 extents found\n")

    def test_ext4_reserves_without_writing(self):
        runner = SwapRunner({"filefrag": EXT4_FILEFRAG})
        self.assertEqual(worker.create_swapfile(runner, "/mnt/agi-os", "ext4", 16 * GIB), 1605632)
        tools = [c[0] for c in runner.calls]
        self.assertEqual(tools, ["mkdir", "fallocate", "chmod", "mkswap", "filefrag"])
        self.assertIn(str(16 * GIB), runner.calls[1])
        self.assertNotIn("dd", tools)

    def test_btrfs_uses_subvolume_and_mkswapfile(self):
        runner = SwapRunner({"map-swapfile": "198656\n"})
        self.assertEqual(worker.create_swapfile(runner, "/mnt/agi-os", "btrfs", 8 * GIB), 198656)
        self.assertEqual(runner.calls[0], ["btrfs", "subvolume", "create", "/mnt/agi-os/swap"])
        self.assertIn(["btrfs", "filesystem", "mkswapfile", "--size", "8g", "/mnt/agi-os/swap/swapfile"], runner.calls)
        with self.assertRaises(ValidationError):
            worker.create_swapfile(SwapRunner({"map-swapfile": "ERROR: not a swap file\n"}), "/mnt/agi-os", "btrfs", GIB)

    def test_kernel_parameters(self):
        resume = worker.resume_parameter("fs-uuid", 42)
        self.assertEqual(worker.boot_options("root-uuid"), "root=UUID=root-uuid rw")
        self.assertEqual(worker.boot_options("root-uuid", None, resume), "root=UUID=root-uuid rw resume=UUID=fs-uuid resume_offset=42")
        self.assertEqual(worker.boot_options("root-uuid", "luks", resume),
                         "cryptdevice=UUID=luks:cryptroot root=/dev/mapper/cryptroot rw resume=UUID=fs-uuid resume_offset=42")
        grub = worker.grub_defaults('GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX=""\nGRUB_CMDLINE_LINUX_DEFAULT="quiet"\n', "luks", resume)
        self.assertEqual(grub.count("GRUB_CMDLINE_LINUX="), 1)
        self.assertIn('GRUB_CMDLINE_LINUX="cryptdevice=UUID=luks:cryptroot resume=UUID=fs-uuid resume_offset=42"', grub)
        self.assertIn('GRUB_CMDLINE_LINUX_DEFAULT="quiet"', grub)


class InstallRunner(SwapRunner):
    def __init__(self, config):
        super().__init__({"filefrag": EXT4_FILEFRAG})
        self.config = config

    def run(self, args, input_text=None, timeout=1800):
        if args[0] == "blkid":
            self.calls.append(args)
            return "installed-uuid\n"
        if args[0] == "genfstab":
            self.calls.append(args)
            return "UUID=installed-uuid / ext4 defaults 0 1\n"
        if "-Qq" in args:
            self.calls.append(args)
            return "\n".join(worker.packages_for(self.config, demo_inventory()["hardware"]))
        return super().run(args, input_text, timeout)


class InstallTests(unittest.TestCase):
    def install(self, swap, virtualization="none"):
        config = Configuration.parse(specification(swap=swap, session="", packages=[], services=[]))
        snapshot = demo_inventory()
        disk = snapshot["disks"][0]
        request = {"configuration": config.as_dict(), "fingerprint": disk["fingerprint"],
                   "consent_digest": config.digest(), "password": "private-password",
                   "hardware": {**snapshot["hardware"], "memory": int(15.3 * GIB), "virtualization": virtualization}}
        runner, events = InstallRunner(config), []
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            # kbd is part of the base system; the worker checks the console files exist there (CMP-122).
            for name in (f"keymaps/i386/qwerty/{config.effective_keymap()}.map.gz",
                         f"consolefonts/{config.effective_console_font()}.psfu.gz"):
                (target / "usr/share/kbd" / name).parent.mkdir(parents=True, exist_ok=True)
                (target / "usr/share/kbd" / name).touch()
            with patch.object(worker, "TARGET", target), patch.object(worker, "preflight", return_value=(config, snapshot, disk)), \
                 patch.object(worker, "inventory", return_value=snapshot), patch.object(worker.Catalog, "validate", side_effect=lambda p: p), \
                 patch.object(worker, "emit", side_effect=lambda kind, **data: events.append({"kind": kind, **data})), \
                 patch.object(worker.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
                worker.install(request, runner)
            files = {path: (target / path).read_text() for path in
                     ("etc/fstab", "boot/loader/entries/agi-os.conf", "boot/loader/entries/agi-os-fallback.conf",
                      "var/lib/agi-os/installation.json", "etc/mkinitcpio.conf.d/agi-os.conf", worker.HIBERNATE_MODE_FILE)
                     if (target / path).exists()}
        self.assertEqual(events[-1]["kind"], "installed")
        return runner.calls, files

    def test_hibernate_configures_swapfile_fstab_resume_and_initramfs(self):
        calls, files = self.install("hibernate")
        fallocate = next(c for c in calls if c[0] == "fallocate")
        self.assertIn(str(16 * GIB), fallocate)  # the real computer's RAM, not the preview VM's
        self.assertLess(calls.index(fallocate), next(i for i, c in enumerate(calls) if c[0] == "genfstab"))
        self.assertIn("/swap/swapfile none swap defaults,pri=10 0 0", files["etc/fstab"])
        for entry in ("boot/loader/entries/agi-os.conf", "boot/loader/entries/agi-os-fallback.conf"):
            self.assertIn("resume=UUID=installed-uuid resume_offset=1605632", files[entry])
        self.assertIn(" resume ", files["etc/mkinitcpio.conf.d/agi-os.conf"])
        record = json.loads(files["var/lib/agi-os/installation.json"])
        self.assertEqual(record["swap"], "hibernate")
        self.assertEqual(record["hibernation"], {"file": "/swap/swapfile", "size": 16 * GIB,
                                                 "resume_uuid": "installed-uuid", "resume_offset": 1605632, "mode": "platform"})
        self.assertNotIn(worker.HIBERNATE_MODE_FILE, files)  # real firmware keeps ACPI S4 (platform mode)

    def test_virtual_machine_hibernates_in_shutdown_mode(self):
        """QEMU turns ACPI S4 into a delayed power-off; the kernel then rolls the image back."""
        _, files = self.install("hibernate", virtualization="kvm")
        self.assertEqual(files[worker.HIBERNATE_MODE_FILE], "[Sleep]\nHibernateMode=shutdown\n")
        self.assertEqual(json.loads(files["var/lib/agi-os/installation.json"])["hibernation"]["mode"], "shutdown")

    def test_zram_only_leaves_no_swapfile_or_resume(self):
        calls, files = self.install("zram")
        self.assertFalse([c for c in calls if c[0] in ("fallocate", "mkswap", "filefrag")])
        self.assertNotIn("swap", files["etc/fstab"])
        self.assertNotIn("resume", files["boot/loader/entries/agi-os.conf"])
        self.assertIsNone(json.loads(files["var/lib/agi-os/installation.json"])["hibernation"])


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for path, text in {"proc/sys/kernel/random/boot_id": "boot-one",
                           "proc/swaps": "Filename Type Size Used Priority\n/dev/zram0 partition 1 0 100\n"
                                         "/swap/swapfile file 16777212 0 10\n",
                           "proc/cmdline": "root=UUID=r rw resume=UUID=fs resume_offset=42\n",
                           "sys/power/resume": "254:0\n", "sys/power/resume_offset": "42\n"}.items():
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text(text)
        (self.root / "dev/shm").mkdir(parents=True)
        (self.root / "etc").mkdir()
        (self.root / "etc/locale.conf").write_text("LANG=ru_RU.UTF-8\n")
        self.record = {"id": "rec", "hibernation": {"file": "/swap/swapfile", "size": 16 * GIB,
                                                   "resume_uuid": "fs", "resume_offset": 42}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_configuration_checks(self):
        with patch.object(verify, "command", return_value=(0, 's "yes"')):
            checks = verify.hibernation_checks(self.record, {}, self.root)
        self.assertTrue(checks["Hibernation: swap file on"])
        self.assertTrue(checks["Hibernation: resume in the kernel parameters"])
        self.assertTrue(checks["Hibernation: available to the system (logind)"])
        self.assertFalse(checks["Hibernation: session restored (agi-os-verify --hibernate)"])
        (self.root / "sys/power/resume_offset").write_text("0\n")
        with patch.object(verify, "command", return_value=(0, 's "na"')):
            checks = verify.hibernation_checks(self.record, {}, self.root)
        self.assertFalse(checks["Hibernation: resume in the kernel parameters"])
        self.assertFalse(checks["Hibernation: available to the system (logind)"])

    def test_resumed_session_passes(self):
        state = self.root / "state"
        ticks = iter([(1000.0, 0.0), (1001.0, 0.0), (1300.0, 290.0)])
        with patch.object(verify, "command", return_value=(0, "")), patch.object(verify, "clocks", side_effect=lambda: next(ticks)), \
                patch.object(verify.time, "sleep"):
            passed, detail = verify.hibernate(self.record, state, self.root)
        self.assertTrue(passed, detail)
        self.assertTrue(json.loads((state / "acceptance.json").read_text())["hibernate"]["result"])
        self.assertFalse(list((self.root / "dev/shm").iterdir()))

    def test_rolled_back_hibernation_is_not_a_resume(self):
        """Run A: the session went on in the same boot after the kernel rolled back; not a pass."""
        state = self.root / "state"
        log = "PM: hibernation: Creating image:\nPM: Wakeup event detected during hibernation, rolling back.\n"
        for output, gap in ((log, 290.0), ("", 2.0)):
            ticks = iter([(1000.0, 0.0), (1001.0, 0.0), (1004.0, gap)])
            def command(args, output=output):
                return (1, "none") if args[0] == "systemd-detect-virt" else (0, output)
            with self.subTest(gap=gap), patch.object(verify, "command", side_effect=command), \
                    patch.object(verify, "clocks", side_effect=lambda: next(ticks)), patch.object(verify.time, "sleep"):
                passed, detail = verify.hibernate(self.record, state, self.root)
                self.assertFalse(passed, detail)
                self.assertFalse(json.loads((state / "acceptance.json").read_text())["hibernate"]["result"])
        self.assertIn("Hibernation not confirmed", detail)

    def test_unreadable_kernel_log_is_not_a_pass(self):
        state = self.root / "state"
        ticks = iter([(1000.0, 0.0), (1001.0, 0.0), (1300.0, 290.0)])
        def command(args):
            return (1, "") if args[0] == "journalctl" else (0, "")
        with patch.object(verify, "command", side_effect=command), patch.object(verify, "clocks", side_effect=lambda: next(ticks)), \
                patch.object(verify.time, "sleep"):
            passed, detail = verify.hibernate(self.record, state, self.root)
        self.assertFalse(passed)
        self.assertIn("kernel log is unavailable", detail)

    def test_preview_vm_does_not_try_platform_hibernation(self):
        calls = []
        def command(args):
            calls.append(args)
            return (0, "kvm") if args[0] == "systemd-detect-virt" else (0, "")
        record = {**self.record, "hibernation": {**self.record["hibernation"], "mode": "platform"}}
        with patch.object(verify, "command", side_effect=command):
            passed, detail = verify.hibernate(record, self.root / "state", self.root)
        self.assertFalse(passed)
        self.assertIn("checked after installing", detail)
        self.assertNotIn(["systemctl", "hibernate"], calls)

    def test_refusal_and_fresh_boot_fail(self):
        state = self.root / "state"
        with patch.object(verify, "command", return_value=(1, "Not enough suitable swap space")), patch.object(verify.time, "sleep"):
            passed, detail = verify.hibernate(self.record, state, self.root)
        self.assertFalse(passed)
        self.assertIn("swap", detail)
        # A run that never returned (the computer booted afresh) fails on the next evaluation.
        (state / "acceptance.json").write_text(json.dumps({"hibernate": {"boot_id": "boot-one", "result": None}}))
        (self.root / "proc/sys/kernel/random/boot_id").write_text("boot-two")
        record = {**self.record, "configuration": specification(swap="hibernate"), "root_uuid": "r", "packages": []}
        with patch.object(verify, "command", return_value=(0, "")), patch.object(verify.getpass, "getuser", return_value="someone-else"), \
                patch.object(verify.socket, "getaddrinfo", return_value=[]):
            result = verify.evaluate(record, state, False, self.root)
        self.assertFalse(result["hibernate"]["result"])
        self.assertIn("booted afresh", result["hibernate"]["detail"])


if __name__ == "__main__":
    unittest.main()
