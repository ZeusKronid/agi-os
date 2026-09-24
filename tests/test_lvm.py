"""LVM on request, also inside LUKS (CMP-154): configuration, layout, installation, finalization."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import layout
import test_hibernation
import worker
from domain import Configuration, ValidationError
from hardware import initramfs_config
from system import demo_inventory


def plan_config(lvm=True, filesystem="ext4"):
    return SimpleNamespace(filesystem=filesystem, partition_table="gpt", bootloader="systemd-boot", lvm=lvm)


class Recorder:
    def __init__(self, answers=None):
        self.calls, self.answers = [], answers or {}

    def run(self, args, input_text=None, **kw):
        self.calls.append(args)
        return self.answers.get(args[0], "")


class ConfigurationTests(unittest.TestCase):
    def test_lvm_is_an_explicit_choice_off_for_older_records(self):
        data = test_hibernation.specification()
        old = Configuration.parse({k: v for k, v in data.items() if k != "lvm"})
        self.assertFalse(old.lvm)
        chosen = Configuration.parse({**data, "lvm": True})
        self.assertTrue(chosen.lvm)
        self.assertNotEqual(chosen.digest(), old.digest())
        self.assertEqual(Configuration.parse(chosen.as_dict()), chosen)
        disk = {"size": 64 * 2**30}
        self.assertIn("LVM logical volume", chosen.summary(disk))
        self.assertNotIn("LVM", old.summary(disk))
        with self.assertRaises(ValidationError):
            Configuration.parse({**data, "lvm": "yes"})


class LayoutTests(unittest.TestCase):
    def test_each_installation_gets_its_own_volume_group(self):
        first, second = layout.plan_for(plan_config(), "uefi"), layout.plan_for(plan_config(), "uefi")
        self.assertTrue(first.lvm)
        self.assertNotEqual(first.group, second.group)
        self.assertRegex(first.group, r"^agi[0-9a-f]{8}$")
        self.assertIsNone(layout.plan_for(plan_config(lvm=False), "uefi").group)
        self.assertTrue(layout.plan_for(SimpleNamespace(filesystem="ext4", partition_table="msdos", bootloader="grub",
                                                        lvm=True), "bios").lvm)

    def test_plain_lvm_root(self):
        runner, plan = Recorder(), layout.plan_for(plan_config(), "uefi")
        device = layout.create_root(runner, plan, "/dev/vda2", "")
        self.assertEqual(device, f"/dev/{plan.group}/root")
        self.assertEqual(runner.calls, [["pvcreate", "--yes", "/dev/vda2"], ["vgcreate", plan.group, "/dev/vda2"],
                                        ["lvcreate", "--yes", "--extents", "100%FREE", "--name", "root", plan.group],
                                        ["mkfs.ext4", "-F", device]])

    def test_lvm_inside_luks(self):
        runner, plan = Recorder(), layout.plan_for(plan_config(filesystem="btrfs"), "uefi", encrypted=True)
        device = layout.create_root(runner, plan, "/dev/vda2", "secret-pass")
        # btrfs subvolumes (CMP-153) follow on the logical volume.
        self.assertEqual([c[:2] for c in runner.calls[:6]], [["cryptsetup", "luksFormat"], ["cryptsetup", "open"],
                                                         ["pvcreate", "--yes"], ["vgcreate", plan.group], ["lvcreate", "--yes"],
                                                         ["mkfs.btrfs", "-f"]])
        self.assertEqual(runner.calls[2][-1], "/dev/mapper/cryptroot")
        self.assertEqual(runner.calls[5][-1], device)
        self.assertEqual(runner.calls[6][-2], device)  # the subvolumes are created on the logical volume
        self.assertTrue(all("secret-pass" not in c for c in runner.calls))

    def test_activate_root_finds_the_group_of_an_existing_root(self):
        runner = Recorder({"blkid": "LVM2_member\n", "pvs": "  agi1a2b3c4d\n"})
        self.assertEqual(layout.activate_root(runner, "/dev/mapper/src"), ("agi1a2b3c4d", "/dev/agi1a2b3c4d/root"))
        self.assertEqual(runner.calls[-1], ["vgchange", "--activate", "y", "agi1a2b3c4d"])
        self.assertIsNone(layout.activate_root(Recorder({"blkid": "ext4\n"}), "/dev/vda2"))
        with self.assertRaises(ValidationError):
            layout.activate_root(Recorder({"blkid": "LVM2_member\n", "pvs": "\n"}), "/dev/vda2")
        warned = Recorder({"blkid": "LVM2_member\n", "pvs": "  WARNING: PV /dev/nbd0p2 has an old header.\n  agi00c0ffee\n"})
        self.assertEqual(layout.activate_root(warned, "/dev/nbd0p2")[0], "agi00c0ffee")

    def test_initramfs_activates_the_group_between_encrypt_and_resume(self):
        hooks = initramfs_config({}, True, True, lvm=True).split("HOOKS=(")[1].split(")")[0].split()
        self.assertLess(hooks.index("encrypt"), hooks.index("lvm2"))
        self.assertLess(hooks.index("lvm2"), hooks.index("resume"))
        self.assertLess(hooks.index("resume"), hooks.index("filesystems"))
        self.assertIn(" lvm2 ", initramfs_config({}, False, False, lvm=True))
        self.assertNotIn("lvm2", initramfs_config({}, True, True))

    def test_boot_options_find_the_logical_volume_by_uuid(self):
        self.assertEqual(worker.boot_options("fs-uuid", "luks-uuid", None, lvm=True),
                         "cryptdevice=UUID=luks-uuid:cryptroot root=UUID=fs-uuid rw")
        self.assertEqual(worker.boot_options("fs-uuid", None, None, lvm=True), "root=UUID=fs-uuid rw")
        self.assertEqual(worker.boot_options("fs-uuid", "luks-uuid"), "cryptdevice=UUID=luks-uuid:cryptroot root=/dev/mapper/cryptroot rw")


class InstallTests(unittest.TestCase):
    def test_encrypted_lvm_with_hibernation(self):
        config = Configuration.parse(test_hibernation.specification(swap="hibernate", session="", packages=[], services=[],
                                                                    lvm=True))
        snapshot = demo_inventory()
        disk = snapshot["disks"][0]
        request = {"configuration": config.as_dict(), "fingerprint": disk["fingerprint"], "consent_digest": config.digest(),
                   "password": "private-password", "passphrase": "private-passphrase",
                   "hardware": {**snapshot["hardware"], "memory": 16 * 2**30, "virtualization": "none"}}
        runner, events = test_hibernation.InstallRunner(config), []
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target"
            for name in (f"keymaps/i386/qwerty/{config.effective_keymap()}.map.gz",
                         f"consolefonts/{config.effective_console_font()}.psfu.gz"):
                (target / "usr/share/kbd" / name).parent.mkdir(parents=True, exist_ok=True)
                (target / "usr/share/kbd" / name).touch()
            with patch.object(worker, "TARGET", target), patch.object(worker, "preflight", return_value=(config, snapshot, disk)), \
                 patch.object(worker, "inventory", return_value=snapshot), patch.object(worker.Catalog, "validate", side_effect=lambda p: p), \
                 patch.object(worker, "emit", side_effect=lambda kind, **data: events.append({"kind": kind, **data})), \
                 patch.object(worker.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as system:
                worker.install(request, runner)
            entry = (target / "boot/loader/entries/agi-os.conf").read_text()
            hooks = (target / "etc/mkinitcpio.conf.d/agi-os.conf").read_text()
            record = json.loads((target / "var/lib/agi-os/installation.json").read_text())
        self.assertEqual(events[-1]["kind"], "installed")
        group = next(c[1] for c in runner.calls if c[0] == "vgcreate")
        volume = f"/dev/{group}/root"
        self.assertEqual(next(c for c in runner.calls if c[0] == "pvcreate")[-1], "/dev/mapper/cryptroot")
        self.assertIn(["mkfs.ext4", "-F", volume], runner.calls)
        self.assertIn(["mount", volume, str(target)], runner.calls)
        self.assertIn("cryptdevice=UUID=installed-uuid:cryptroot root=UUID=installed-uuid rw", entry)
        self.assertIn("resume=UUID=installed-uuid", entry)
        self.assertIn("encrypt lvm2 resume", hooks)
        self.assertIn("lvm2", record["packages"])
        self.assertTrue(record["configuration"]["lvm"])
        # The group goes inactive when the installation is released (before LUKS closes).
        self.assertIn(["vgchange", "--activate", "n", group], [c.args[0] for c in system.call_args_list])


class FinalizeTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "web"))
        import finalize_worker
        self.finalize_worker = finalize_worker

    def test_the_preview_group_is_opened_and_closed_with_its_root(self):
        runner = Recorder({"blkid": "LVM2_member\n", "pvs": "agi0badcafe\n"})
        source = self.finalize_worker.Source(runner, {"format": "raw", "path": "/dev/sdb2"})
        source.device = "/dev/nbd0"
        device, encrypted = source.open_root(2, "")
        self.assertEqual((device, encrypted, source.group), ("/dev/agi0badcafe/root", False, "agi0badcafe"))
        source.close_root()
        self.assertEqual(runner.calls[-1], ["vgchange", "--activate", "n", "agi0badcafe"])
        self.assertIsNone(source.group)

    def test_record_and_preview_must_agree_on_lvm(self):
        data = test_hibernation.specification(lvm=True)
        config = Configuration.parse(data)
        record = {"configuration": data, "firmware": "uefi", "encrypted": False}
        self.finalize_worker.check_record(record, config, "uefi", False, True)
        with self.assertRaises(ValidationError):
            self.finalize_worker.check_record(record, config, "uefi", False, False)


if __name__ == "__main__":
    unittest.main()
