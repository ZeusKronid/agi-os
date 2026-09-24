"""The disk layout plan (CMP-123): what worker.install and finalize_worker create."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

APP = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
import layout
from domain import GIB, ValidationError


class Recorder:
    def __init__(self):
        self.calls = []

    def run(self, args, input_text=None, **kw):
        self.calls.append((args, input_text))
        return ""


def config(filesystem="ext4"):
    return SimpleNamespace(filesystem=filesystem)


class PlanTests(unittest.TestCase):
    def test_uefi_whole_disk(self):
        plan = layout.plan_for(config(), "uefi")
        self.assertEqual(plan.table, "gpt")
        self.assertEqual([(p.number, p.role, p.typecode, p.name) for p in plan.partitions],
                         [(1, "boot", "ef00", "AGI-BOOT"), (2, "root", "8300", "AGI-ROOT")])
        self.assertEqual(plan.part("boot").size, GIB)
        self.assertEqual(plan.part("boot").filesystem, "vfat")
        self.assertEqual(plan.path("/dev/nvme0n1", "root"), "/dev/nvme0n1p2")

    def test_bios_whole_disk_keeps_the_grub_core_partition_first(self):
        plan = layout.plan_for(config(), "bios")
        self.assertEqual([(p.number, p.role, p.typecode) for p in plan.partitions],
                         [(1, "bios", "ef02"), (2, "boot", "8300"), (3, "root", "8300")])
        self.assertEqual(plan.part("boot").filesystem, "ext4")
        self.assertEqual(plan.path("/dev/vda", "boot"), "/dev/vda2")

    def test_unknown_firmware_is_refused(self):
        with self.assertRaises(ValidationError):
            layout.plan_for(config(), "coreboot")

    def test_table_commands_match_the_previous_layout(self):
        commands = layout.table_commands(layout.plan_for(config(), "bios"), "/dev/vda")
        self.assertEqual(commands, [
            ["sgdisk", "--zap-all", "/dev/vda"],
            ["sgdisk", "--new=1:0:+2M", "--typecode=1:ef02", "--change-name=1:BIOS",
             "--new=2:0:+1024M", "--typecode=2:8300", "--change-name=2:AGI-BOOT",
             "--new=3:0:0", "--typecode=3:8300", "--change-name=3:AGI-ROOT", "/dev/vda"]])

    def test_root_stack(self):
        runner = Recorder()
        plain = layout.plan_for(config("btrfs"), "uefi")
        self.assertEqual(layout.create_root(runner, plain, "/dev/vda2", ""), "/dev/vda2")
        self.assertEqual(runner.calls, [(["mkfs.btrfs", "-f", "/dev/vda2"], None)])
        runner = Recorder()
        encrypted = layout.plan_for(config(), "uefi", encrypted=True)
        self.assertEqual(layout.create_root(runner, encrypted, "/dev/vda2", "secret-pass"), "/dev/mapper/cryptroot")
        self.assertEqual([c[0][:2] for c in runner.calls], [["cryptsetup", "luksFormat"], ["cryptsetup", "open"],
                                                             ["mkfs.ext4", "-F"]])
        # The passphrase goes only over stdin, never into arguments.
        self.assertTrue(all("secret-pass" not in args for args, _ in runner.calls))
        self.assertEqual([c[1] for c in runner.calls[:2]], ["secret-pass", "secret-pass"])

    def test_unknown_root_filesystem_is_refused(self):
        with self.assertRaises(KeyError):
            layout.create_root(Recorder(), layout.plan_for(config("vfat"), "uefi"), "/dev/vda2", "")


if __name__ == "__main__":
    unittest.main()
