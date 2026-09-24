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
# sgdisk type codes. XBOOTLDR: /boot next to an ESP shared with other systems.
BIOS_BOOT, ESP, LINUX, XBOOTLDR = "ef02", "ef00", "8300", "ea00"
# MBR (msdos) partition type of Linux file systems.
MBR_LINUX = "83"
# MBR entries hold 32-bit sector numbers: nothing may end beyond 2 TiB.
MBR_SECTORS = 2**32
SECTOR = 512
ESP_GUID = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
MKFS_FORCE = {"ext4": "-F", "btrfs": "-f", "xfs": "-f", "f2fs": "-f"}


def partition_path(disk, number):
    return disk + ("p" if disk[-1].isdigit() else "") + str(number)


@dataclass(frozen=True)
class Partition:
    number: int
    role: str        # "bios" (GRUB core on BIOS/GPT), "boot" (/boot) or "root"
    size: int | None  # bytes; None takes the rest of the disk
    typecode: str    # sgdisk code on GPT, MBR type byte (hex) on msdos
    name: str        # GPT partition name; MBR entries have none
    filesystem: str | None  # of the partition itself; the root's is in the plan's stack


@dataclass(frozen=True)
class Plan:
    firmware: str
    table: str
    partitions: tuple
    encrypted: bool
    filesystem: str
    # Dual boot (CMP-151): the disk's existing ESP holds the boot loader, next to Windows
    # Boot Manager; this system's /boot becomes an XBOOTLDR partition.
    shared_esp: bool = False

    def part(self, role):
        return next(p for p in self.partitions if p.role == role)

    def path(self, disk, role):
        return partition_path(disk, self.part(role).number)


def plan_for(config, firmware, encrypted=False, shared_esp=False):
    """The layout of this configuration for the firmware: a whole disk, or with shared_esp
    the system's partitions next to other systems that keep their ESP."""
    if firmware not in ("uefi", "bios"):
        raise ValidationError("Unknown firmware type")
    if shared_esp and (firmware != "uefi" or config.bootloader != "systemd-boot"):
        raise ValidationError("Only systemd-boot on UEFI shares the existing EFI system partition")
    if getattr(config, "partition_table", "gpt") == "msdos":
        if firmware != "bios" or config.bootloader != "grub":
            raise ValidationError("An MBR (msdos) disk is set up only for BIOS computers with GRUB; UEFI needs GPT")
        # GRUB's core image goes to the gap after the MBR (partitions start at 1 MiB);
        # /boot is the active partition for BIOSes that look for one.
        parts = (Partition(1, "boot", BOOT_SIZE, MBR_LINUX, "", "ext4"),
                 Partition(2, "root", None, MBR_LINUX, "", None))
        return Plan(firmware, "msdos", parts, bool(encrypted), config.filesystem)
    parts = []
    if firmware == "bios":
        parts.append(Partition(1, "bios", BIOS_BOOT_SIZE, BIOS_BOOT, "BIOS", None))
    number = len(parts) + 1
    boot_type = XBOOTLDR if shared_esp else ESP if firmware == "uefi" else LINUX
    parts.append(Partition(number, "boot", BOOT_SIZE, boot_type, "AGI-BOOT",
                           "vfat" if firmware == "uefi" else "ext4"))
    parts.append(Partition(number + 1, "root", None, LINUX, "AGI-ROOT", None))
    return Plan(firmware, "gpt", tuple(parts), bool(encrypted), config.filesystem, bool(shared_esp))


def mbr_script(entries):
    """sfdisk input for MBR entries (start sector or None, size in sectors or None, type,
    active); None lets sfdisk align the start or take the rest of the free space."""
    lines = []
    for start, size, typecode, active in entries:
        fields = [f"start={start}" if start is not None else "", f"size={size}" if size is not None else "",
                  f"type={typecode}", "bootable" if active else ""]
        lines.append(", ".join(f for f in fields if f))
    return "\n".join(lines) + "\n"


def check_mbr_size(disk_size):
    if disk_size // SECTOR > MBR_SECTORS:
        raise ValidationError("An MBR (msdos) table covers only the first 2 TiB of this disk; choose GPT")


def apply_table(runner, plan, disk, disk_size=None):
    """Replace the disk's table with the plan's partitions."""
    if plan.table == "msdos":
        if disk_size is not None:
            check_mbr_size(disk_size)
        runner.run(["sgdisk", "--zap-all", disk])
        entries = [(None, None if p.size is None else p.size // SECTOR, p.typecode, p.role == "boot")
                   for p in plan.partitions]
        runner.run(["sfdisk", "--wipe", "always", "--label", "dos", disk], input_text=mbr_script(entries))
        return
    for command in table_commands(plan, disk):
        runner.run(command)


def table_commands(plan, disk):
    """Commands that replace the disk's GPT with the plan's partitions."""
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
