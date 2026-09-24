"""Disk layout plan: what the installer creates on a disk, apart from how it is written.

One place per storage layer, so the CMP-123 tasks each extend their own:

- table: "gpt" today; msdos for BIOS and existing MBR disks (CMP-152);
- partitions: number, role, size, type, name and file system of each entry;
- root stack, bottom up: optional LUKS2 → (LVM, CMP-154) → file system →
  (btrfs subvolumes, CMP-153);
- partitions of other systems kept on the disk and a shared ESP (dual boot, CMP-151).

The preview installation (worker.install) writes the plan to its virtual disk; the
finalization (finalize_worker) reads the preview through the same plan and rebuilds it
on the computer's disk (copy) or turns its partitions into real ones (promote).
Functions here only build commands and run them through the caller's runner.
"""
from dataclasses import dataclass

from domain import GIB, ValidationError

MIB = 2**20
CRYPT_NAME = "cryptroot"
BOOT_SIZE = GIB
BIOS_BOOT_SIZE = 2 * MIB
# sgdisk type codes.
BIOS_BOOT, ESP, LINUX = "ef02", "ef00", "8300"
MKFS_FORCE = {"ext4": "-F", "btrfs": "-f", "xfs": "-f", "f2fs": "-f"}


def partition_path(disk, number):
    return disk + ("p" if disk[-1].isdigit() else "") + str(number)


@dataclass(frozen=True)
class Partition:
    number: int
    role: str        # "bios" (GRUB core on BIOS/GPT), "boot" (/boot) or "root"
    size: int | None  # bytes; None takes the rest of the disk
    typecode: str
    name: str
    filesystem: str | None  # of the partition itself; the root's is in the plan's stack


@dataclass(frozen=True)
class Plan:
    firmware: str
    table: str
    partitions: tuple
    encrypted: bool
    filesystem: str

    def part(self, role):
        return next(p for p in self.partitions if p.role == role)

    def path(self, disk, role):
        return partition_path(disk, self.part(role).number)


def plan_for(config, firmware, encrypted=False):
    """The layout of a whole-disk installation for this configuration and firmware."""
    if firmware not in ("uefi", "bios"):
        raise ValidationError("Unknown firmware type")
    parts = []
    if firmware == "bios":
        parts.append(Partition(1, "bios", BIOS_BOOT_SIZE, BIOS_BOOT, "BIOS", None))
    number = len(parts) + 1
    parts.append(Partition(number, "boot", BOOT_SIZE, ESP if firmware == "uefi" else LINUX, "AGI-BOOT",
                           "vfat" if firmware == "uefi" else "ext4"))
    parts.append(Partition(number + 1, "root", None, LINUX, "AGI-ROOT", None))
    return Plan(firmware, "gpt", tuple(parts), bool(encrypted), config.filesystem)


def table_commands(plan, disk):
    """Commands that replace the disk's table with the plan's partitions."""
    args = ["sgdisk"]
    for part in plan.partitions:
        end = "0" if part.size is None else f"+{part.size // MIB}M"
        args += [f"--new={part.number}:0:{end}", f"--typecode={part.number}:{part.typecode}",
                 f"--change-name={part.number}:{part.name}"]
    return [["sgdisk", "--zap-all", disk], args + [disk]]


def mkfs_command(filesystem, device):
    if filesystem == "vfat":
        return ["mkfs.fat", "-F", "32", device]
    return ["mkfs." + filesystem, MKFS_FORCE[filesystem], device]


def format_boot(runner, plan, device):
    runner.run(mkfs_command(plan.part("boot").filesystem, device))


def create_root(runner, plan, partition, passphrase, crypt_name=CRYPT_NAME):
    """Build the root stack on its partition; returns the device the file system is on."""
    device = partition
    if plan.encrypted:
        # The passphrase travels only over stdin; a trailing newline would become part of the key.
        runner.run(["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", "--key-file", "-", partition],
                   input_text=passphrase)
        runner.run(["cryptsetup", "open", "--key-file", "-", partition, crypt_name], input_text=passphrase)
        device = "/dev/mapper/" + crypt_name
    runner.run(["mkfs." + plan.filesystem, MKFS_FORCE[plan.filesystem], device])
    return device


def mount_root(runner, plan, device, target):
    runner.run(["mount", device, str(target)])


def mount_boot(runner, plan, device, target):
    (target / "boot").mkdir(exist_ok=True)
    runner.run(["mount", device, str(target / "boot")])
