"""btrfs subvolumes, snapshots before updates and rollback (CMP-153)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
import layout
import update
import worker


class Recorder:
    def __init__(self, on_run=None):
        self.calls, self.on_run = [], on_run

    def run(self, args, input_text=None, **kw):
        self.calls.append(args)
        return self.on_run(args) if self.on_run else ""


def config(filesystem="btrfs", swap="zram", bootloader="systemd-boot"):
    return SimpleNamespace(filesystem=filesystem, swap=swap, bootloader=bootloader)


class SubvolumeLayoutTests(unittest.TestCase):
    def test_btrfs_gets_the_standard_subvolumes(self):
        plan = layout.plan_for(config(), "uefi")
        self.assertEqual([name for name, _ in plan.subvolumes], ["@", "@home", "@log", "@pkg", "@snapshots"])
        self.assertEqual(dict(plan.subvolumes)["@log"], "var/log")
        hibernating = layout.plan_for(config(swap="hibernate"), "uefi")
        self.assertEqual(hibernating.subvolumes[-1], ("@swap", "swap"))
        self.assertEqual(layout.plan_for(config("ext4"), "uefi").subvolumes, ())

    def test_create_root_makes_every_subvolume_on_the_top_level(self):
        runner = Recorder()
        plan = layout.plan_for(config(swap="hibernate"), "bios", encrypted=False)
        self.assertEqual(layout.create_root(runner, plan, "/dev/vda3", ""), "/dev/vda3")
        self.assertEqual(runner.calls[0], ["mkfs.btrfs", "-f", "/dev/vda3"])
        self.assertEqual(runner.calls[1][:2], ["mount", "/dev/vda3"])
        created = [args[-1].rsplit("/", 1)[1] for args in runner.calls if args[:3] == ["btrfs", "subvolume", "create"]]
        self.assertEqual(created, ["@", "@home", "@log", "@pkg", "@snapshots", "@swap"])
        self.assertEqual(runner.calls[-1][0], "umount")
        self.assertFalse(Path(runner.calls[1][2]).exists())  # the temporary mount point is gone

    def test_mount_root_mounts_each_subvolume_in_place(self):
        with tempfile.TemporaryDirectory() as target:
            runner = Recorder()
            layout.mount_root(runner, layout.plan_for(config(), "uefi"), "/dev/mapper/cryptroot", Path(target), "ro")
            self.assertEqual(runner.calls[0], ["mount", "-o", "subvol=@,ro", "/dev/mapper/cryptroot", target])
            self.assertIn(["mount", "-o", "subvol=@pkg,ro", "/dev/mapper/cryptroot", f"{target}/var/cache/pacman/pkg"], runner.calls)
            self.assertTrue((Path(target) / ".snapshots").is_dir())
            runner = Recorder()
            layout.mount_root(runner, layout.plan_for(config("ext4"), "uefi"), "/dev/vda2", Path(target))
            self.assertEqual(runner.calls, [["mount", "/dev/vda2", target]])

    def test_existing_subvolumes_are_read_from_the_disk(self):
        def on_run(args):
            if args[0] == "mount":
                for name in ("@", "@home", "@swap"):
                    (Path(args[-1]) / name).mkdir()
            if args[0] == "umount":
                for child in Path(args[-1]).iterdir():
                    child.rmdir()
            return ""
        found = layout.existing_subvolumes(Recorder(on_run), "/dev/nbd0p2", "btrfs")
        self.assertEqual(found, (("@", ""), ("@home", "home"), ("@swap", "swap")))
        # A flat btrfs root of an older installer keeps its flat layout.
        flat = layout.existing_subvolumes(Recorder(lambda args: ""), "/dev/nbd0p2", "btrfs")
        self.assertEqual(flat, ())
        self.assertEqual(layout.existing_subvolumes(Recorder(), "/dev/vda2", "ext4"), ())

    def test_fstab_and_kernel_options_do_not_pin_subvolume_ids(self):
        text = ("UUID=a / btrfs rw,relatime,ssd,space_cache=v2,subvolid=256,subvol=/@ 0 0\n"
                "UUID=a /home btrfs rw,relatime,subvol=/@home,subvolid=257 0 0\n")
        self.assertNotIn("subvolid", layout.fstab(text))
        self.assertIn("rw,relatime,subvol=/@home 0 0", layout.fstab(text))
        plan = layout.plan_for(config(), "uefi")
        self.assertEqual(worker.boot_options("u", None, None, layout.root_flags(plan)), "root=UUID=u rootflags=subvol=@ rw")
        self.assertEqual(layout.root_flags(layout.plan_for(config("ext4"), "uefi")), [])

    def test_swap_file_uses_the_mounted_swap_subvolume(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "swap").mkdir()
            runner = Recorder(lambda args: "1234\n" if args[:3] == ["btrfs", "inspect-internal", "map-swapfile"] else "")
            self.assertEqual(worker.create_swapfile(runner, root, "btrfs", 4 * 2**30), 1234)
            self.assertNotIn(["btrfs", "subvolume", "create", f"{root}/swap"], runner.calls)


class RollbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.top, self.boot, self.state = base / "top", base / "boot", base / "state"
        self.snapshots = self.top / "@snapshots"
        for path in (self.top / "@", self.snapshots, self.boot):
            path.mkdir(parents=True)
        (self.boot / "vmlinuz-linux").write_text("new kernel")
        patcher = patch.multiple(update, STATE=self.state, STATUS=self.state / "update-status.json",
                                 NOTICE=self.state / "update-notice", LOG=base / "update.log")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls = []

    def fake_run(self, args, **kw):
        self.calls.append(args)
        if args[:3] == ["btrfs", "subvolume", "snapshot"]:
            Path(args[-1]).mkdir()
        if args[:3] == ["btrfs", "subvolume", "delete"]:
            Path(args[-1]).rmdir()
        return ""

    def take(self, stamp):
        with patch.object(update, "run", self.fake_run):
            return update.snapshot(stamp, snapshots=self.snapshots, boot=self.boot)

    def test_snapshot_keeps_the_kernel_images_of_that_moment(self):
        (self.boot / "initramfs-linux.img").write_text("initramfs")
        (self.boot / "loader").mkdir()
        taken = self.take("20260924-100000")
        self.assertEqual(Path(taken).name, "pre-update-20260924-100000")
        copy = self.snapshots / "pre-update-20260924-100000.boot"
        self.assertEqual(sorted(p.name for p in copy.iterdir()), ["initramfs-linux.img", "vmlinuz-linux"])
        self.assertEqual(update.snapshot_names(self.snapshots), ["pre-update-20260924-100000"])

    def test_old_snapshots_go_with_their_kernel_images(self):
        for stamp in ("1", "2", "3", "4"):
            self.take(stamp)
        self.assertEqual(update.snapshot_names(self.snapshots), ["pre-update-2", "pre-update-3", "pre-update-4"])
        self.assertFalse((self.snapshots / "pre-update-1.boot").exists())

    def rollback(self, name=None, root=None):
        with patch.object(update, "run", self.fake_run):
            return update.rollback(name, snapshots=self.snapshots, boot=self.boot, top=self.top,
                                   root=root or {"fstype": "btrfs", "fsroot": "/@", "source": "/dev/mapper/cryptroot"})

    def test_rollback_swaps_the_root_and_restores_the_kernel(self):
        self.take("1")
        (self.boot / "vmlinuz-linux").write_text("updated kernel")
        (self.top / "@rollback-old").mkdir()
        done = self.rollback()
        self.assertEqual(done["snapshot"], "pre-update-1")
        self.assertEqual((self.boot / "vmlinuz-linux").read_text(), "new kernel")
        self.assertTrue((self.top / done["previous_root"]).is_dir())
        self.assertTrue((self.top / "@").is_dir())
        self.assertIn(["mount", "-o", "subvolid=5", "/dev/mapper/cryptroot", str(self.top)], self.calls)
        self.assertIn(["btrfs", "subvolume", "delete", str(self.top / "@rollback-old")], self.calls)
        self.assertEqual(self.calls[-1], ["umount", str(self.top)])
        status = json.loads((self.state / "update-status.json").read_text())
        self.assertTrue(status["reboot_required"])
        self.assertEqual(status["rollback"]["boot"], ["vmlinuz-linux"])

    def test_failed_snapshot_puts_the_root_back(self):
        self.take("1")

        def failing(args, **kw):
            self.calls.append(args)
            if args[:3] == ["btrfs", "subvolume", "snapshot"]:
                raise update.UpdateError("no space")
            return ""
        with patch.object(update, "run", failing), self.assertRaises(update.UpdateError):
            update.rollback(None, snapshots=self.snapshots, boot=self.boot, top=self.top,
                            root={"fstype": "btrfs", "fsroot": "/@", "source": "/dev/vda2"})
        self.assertTrue((self.top / "@").is_dir())
        self.assertFalse(list(self.top.glob("@rollback-*")))
        self.assertEqual(self.calls[-1], ["umount", str(self.top)])

    def test_second_rollback_before_reboot_preserves_running_root(self):
        self.take("1")
        self.rollback()
        calls_before = list(self.calls)
        kept = list(self.top.glob("@rollback-*"))
        with self.assertRaisesRegex(update.UpdateError, "waiting for a restart"):
            self.rollback()
        self.assertEqual(self.calls, calls_before)
        self.assertEqual(list(self.top.glob("@rollback-*")), kept)
        self.assertTrue(kept[0].is_dir())

    def test_rollback_refuses_without_the_layout_or_snapshots(self):
        with self.assertRaises(update.UpdateError):
            self.rollback(root={"fstype": "ext4", "fsroot": "/", "source": "/dev/vda2"})
        with self.assertRaises(update.UpdateError):
            self.rollback()  # no snapshots yet
        self.take("1")
        with self.assertRaises(update.UpdateError):
            self.rollback("../../etc")


if __name__ == "__main__":
    unittest.main()
