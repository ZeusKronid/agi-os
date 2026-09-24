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


def config(filesystem="ext4", table="gpt", bootloader="grub"):
    return SimpleNamespace(filesystem=filesystem, partition_table=table, bootloader=bootloader)


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
        plain = layout.plan_for(config("xfs"), "uefi")
        self.assertEqual(layout.create_root(runner, plain, "/dev/vda2", ""), "/dev/vda2")
        self.assertEqual(runner.calls, [(["mkfs.xfs", "-f", "/dev/vda2"], None)])
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


class MbrTests(unittest.TestCase):
    """CMP-152: an MBR (msdos) table for BIOS computers."""

    def test_bios_msdos_has_active_boot_and_root_without_a_grub_partition(self):
        plan = layout.plan_for(config(table="msdos"), "bios")
        self.assertEqual(plan.table, "msdos")
        self.assertEqual([(p.number, p.role, p.typecode, p.filesystem) for p in plan.partitions],
                         [(1, "boot", "83", "ext4"), (2, "root", "83", None)])
        self.assertEqual(plan.path("/dev/sda", "root"), "/dev/sda2")

    def test_msdos_needs_bios_and_grub(self):
        for firmware, bootloader in (("uefi", "grub"), ("uefi", "systemd-boot"), ("bios", "systemd-boot")):
            with self.subTest(firmware=firmware, bootloader=bootloader), self.assertRaises(ValidationError):
                layout.plan_for(config(table="msdos", bootloader=bootloader), firmware)

    def test_apply_table_writes_an_mbr_through_sfdisk(self):
        runner = Recorder()
        layout.apply_table(runner, layout.plan_for(config(table="msdos"), "bios"), "/dev/sda", 500 * GIB)
        self.assertEqual(runner.calls, [
            (["sgdisk", "--zap-all", "/dev/sda"], None),
            (["sfdisk", "--wipe", "always", "--label", "dos", "/dev/sda"], "size=2097152, type=83, bootable\ntype=83\n")])

    def test_mbr_refuses_disks_beyond_2_tib_before_writing(self):
        runner = Recorder()
        with self.assertRaises(ValidationError):
            layout.apply_table(runner, layout.plan_for(config(table="msdos"), "bios"), "/dev/sda", 3 * 1024 * GIB)
        self.assertEqual(runner.calls, [])

    def test_gpt_apply_table_runs_the_table_commands(self):
        runner, plan = Recorder(), layout.plan_for(config(), "bios")
        layout.apply_table(runner, plan, "/dev/vda", 20 * GIB)
        self.assertEqual([c for c, _ in runner.calls], layout.table_commands(plan, "/dev/vda"))

    def test_configuration_field(self):
        from controller import DemoProvider
        from domain import Configuration
        data = DemoProvider().reply("", [])["configuration"]
        old = {k: v for k, v in data.items() if k != "partition_table"}
        self.assertEqual(Configuration.parse(old).partition_table, "gpt")
        bios = {**data, "bootloader": "grub"}
        mbr = Configuration.parse({**bios, "partition_table": "msdos"})
        self.assertNotEqual(mbr.digest(), Configuration.parse(bios).digest())
        self.assertEqual(Configuration.parse(mbr.as_dict()), mbr)
        self.assertIn("MBR (msdos)", mbr.summary({"size": 64 * GIB}))
        for changes in ({"partition_table": "hybrid"}, {"partition_table": "msdos", "bootloader": "systemd-boot"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                Configuration.parse({**bios, **changes})
