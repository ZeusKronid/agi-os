#!/usr/bin/env python3
"""Privileged finalization: make the approved preview the computer's installed system.

Runs as root inside Live only. Two modes, both leaving the preview intact until
the destination is verified:

- promote: the preview partition lies on the target disk. Its nested partitions
  become real entries of the disk's GPT at the same absolute sectors. No data
  moves; only the partition table changes.
- copy: the preview (image in memory, file on another medium or partition of
  another disk) is copied file by file into fresh partitions on the target disk,
  then verified with a checksum pass.

Afterwards the drivers derived from this computer's real hardware are completed
(the preview was installed for the same inventory, so normally nothing is
missing), the initramfs is rebuilt, the boot loader is registered with the
firmware and a new acceptance ID is recorded.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import replace

from settings import ENGINE
sys.path.insert(0, str(ENGINE))
from domain import SWAPFILE, Configuration, ValidationError, hibernation_swap_size
from hardware import SETUP_MODE_VAR, driver_plan, efi_flag, initramfs_config, profile
from journal import Logger, adopt
import layout
from update import preserve_efi_fallback
from system import inventory, live_environment, selected_disk
from worker import (CRYPT_NAME, Cancelled, Runner, boot_options, create_swapfile, emit, grub_defaults,
                    partition_path, resume_parameter, sbctl_unsigned, swap_fstab_line)
from deployment import restrict_test_targets
import storage_worker

SECTOR = 512
GIB = 2**30
ALIGN = 2048
SOURCE_MAP = 'agi-final-source'
TARGET_MAP = 'agi-final-target'
# Partition table backups made before a table is changed (root-only tmpfs).
BACKUPS = Path('/run')
TYPES = {'bios': layout.BIOS_BOOT, 'boot': layout.ESP, 'linux': layout.LINUX}
# The preview's filesystems were written by the preview VM: read them without trusting
# setuid bits, device nodes or executables on the Live host.
SOURCE_MOUNT = 'ro,nosuid,nodev,noexec'
# The throwaway overlay a dirty preview replays its journal into: tmpfs, not the Live's
# small copy-on-write space under /var/tmp. 4 KiB clusters keep a replay of scattered
# blocks as small as the journal itself.
OVERLAY_DIR = '/tmp'
OVERLAY_CLUSTER = 4096
UNREADABLE = ('The preview’s system could not be opened: its file system is damaged, most likely because the preview '
              'was not shut down properly. Start the preview again, shut it down from its power menu, then repeat '
              'the installation.')
# The last bytes of a swap area's first page while it holds a hibernation image
# (the kernel's swsusp signatures and the uswsusp/TuxOnIce ones).
PAGE = 4096
HIBERNATION_SIGNATURES = (b'S1SUSPEND', b'S2SUSPEND', b'ULSUSPEND', b'LINHIB0001')
LOG = Logger('finalize')
MIB = 2**20
# systemd-boot on a shared ESP: two copies of its ~150 KiB loader and loader.conf.
ESP_ROOM = 2 * MIB
WINDOWS_LOADER = 'EFI/Microsoft/Boot/bootmgfw.efi'
BITLOCKER_NOTE = ('Windows on this disk uses BitLocker. Keep its recovery key at hand: Windows may ask for it once '
                  'because the computer now starts through another boot manager.')


def run_json(runner, args):
    return json.loads(runner.run(args))


def checked_request(request):
    if os.geteuid() != 0 or not live_environment():
        raise ValidationError('Finishing the installation is allowed only inside Live')
    if not isinstance(request, dict) or set(request) != {'target', 'fingerprint', 'configuration', 'passphrase', 'image', 'layout', 'confirmation', 'enroll_keys'}:
        raise ValidationError('Unknown finishing request')
    if not isinstance(request['configuration'], dict) or not all(isinstance(request[k], str) for k in ('target', 'fingerprint', 'confirmation')):
        raise ValidationError('Invalid finishing request')
    config = Configuration.parse(request['configuration'])
    if config.disk != request['target'] or request['confirmation'] != request['target']:
        raise ValidationError('Type the exact path of the target disk to confirm')
    if request['layout'] not in ('erase', 'alongside'):
        raise ValidationError('Unknown layout')
    snapshot = restrict_test_targets(inventory())
    disk = selected_disk(snapshot, request['target'])
    if disk['fingerprint'] != request['fingerprint']:
        raise ValidationError('The disk changed after you confirmed; nothing was finished')
    passphrase = request['passphrase']
    if not isinstance(passphrase, str) or len(passphrase) > 1024 or any(c in passphrase for c in '\n\r\x00'):
        raise ValidationError('Invalid encryption password')
    if type(request['enroll_keys']) is not bool:
        raise ValidationError('Invalid choice for enrolling the Secure Boot keys')
    if request['enroll_keys'] and (config.bootloader != 'systemd-boot' or efi_flag(SETUP_MODE_VAR) is not True):
        # Checked before any disk change: the firmware must accept new keys right now.
        raise ValidationError('The firmware is not in Setup Mode: Secure Boot keys can’t be enrolled. '
                              'Clear the keys in the UEFI settings or untick enrolling the keys')
    request['image'] = checked_image(request['image'], snapshot, disk)
    return config, disk


def checked_image(image, snapshot, target):
    """The preview must be storage the storage helper prepared, never an arbitrary file or device:
    a qcow2 image inside its root-owned mount points, or a partition named AGIOS-PREVIEW."""
    if not isinstance(image, dict) or set(image) != {'format', 'path'} or not isinstance(image['path'], str):
        raise ValidationError('Invalid preview image description')
    path = image['path']
    if image['format'] == 'qcow2':
        allowed = {str(storage_worker.PREVIEW / 'ram/preview.qcow2'),
                   str(storage_worker.PREVIEW / 'media' / storage_worker.NAME / 'preview.qcow2')}
        if path not in allowed or os.path.realpath(path) != path or not Path(path).is_file():
            raise ValidationError('The preview image is outside the prepared storage')
        return {'format': 'qcow2', 'path': path, 'on_target': False}
    if image['format'] == 'raw':
        disk, _ = storage_worker.find_partition(snapshot, path)
        storage_worker.preview_partition(snapshot, disk['path'], path)
        return {'format': 'raw', 'path': path, 'on_target': disk['path'] == target['path']}
    raise ValidationError('Invalid preview image description')


def free_nbd():
    return next((f'/dev/nbd{i}' for i in range(16) if Path(f'/sys/class/block/nbd{i}').exists()
                 and not Path(f'/sys/class/block/nbd{i}/pid').exists()), None)


def nbd_server(device):
    try:
        return int(Path(f'/sys/class/block/{Path(device).name}/pid').read_text())
    except (OSError, ValueError):
        return None


class Source:
    """The preview's partitions and root filesystem, read through a throwaway overlay.

    A preview that was not shut down properly (power cut, crash, a failed hibernation)
    leaves a file system journal to replay. A read-only device cannot replay it, and
    skipping the replay (ext4 noload, xfs norecovery) shows an older and possibly
    inconsistent tree that a copy would then carry to the disk. So the preview (qcow2
    image or raw partition) is exported by qemu-nbd through a temporary qcow2 overlay:
    the kernel replays the journal into the overlay, the preview itself is never
    written, and the overlay is deleted on detach. Mounts stay read-only."""

    def __init__(self, runner, image):
        self.runner, self.image = runner, image
        self.device = None
        self.label = None
        self.nbd = None
        self.scratch = None
        self.opened = False
        self.group = None  # the preview's LVM volume group while it is active
        self.mount = None

    def attach(self):
        self.scratch = Path(tempfile.mkdtemp(prefix='agi-final-overlay-', dir=OVERLAY_DIR))
        overlay = self.scratch / 'overlay.qcow2'
        self.runner.run(['qemu-img', 'create', '-q', '-f', 'qcow2', '-o', f'cluster_size={OVERLAY_CLUSTER}',
                         '-b', self.image['path'], '-F', self.image['format'], str(overlay)])
        self.runner.run(['modprobe', 'nbd', 'max_part=16'])
        nbd = free_nbd()
        if nbd is None:
            raise ValidationError('No free NBD device for the preview image')
        self.runner.run(['qemu-nbd', '--format=qcow2', '--connect', nbd, str(overlay)])
        self.device = self.nbd = nbd
        self.runner.run(['partprobe', self.nbd])
        self.runner.run(['udevadm', 'settle', '--timeout=30'])
        table = run_json(self.runner, ['sfdisk', '--json', self.device])['partitiontable']
        if table.get('label') not in ('gpt', 'dos') or not table.get('partitions'):
            raise ValidationError('The preview has no expected partition table')
        self.label = table['label']
        self.partitions = table['partitions']
        return self

    def partition(self, number):
        return partition_path(self.device, number)

    def open_root(self, root_number, passphrase):
        device = self.partition(root_number)
        kind = self.runner.run(['blkid', '-s', 'TYPE', '-o', 'value', device]).strip()
        if kind == 'crypto_LUKS':
            if not passphrase:
                raise ValidationError('The root is encrypted: enter the encryption password to finish')
            # Writable like the overlay under it: an ext4 or xfs journal replays through it.
            self.runner.run(['cryptsetup', 'open', '--key-file', '-', device, SOURCE_MAP], input_text=passphrase)
            self.opened = True
            return self.volume('/dev/mapper/' + SOURCE_MAP), True
        return self.volume(device), False

    def volume(self, device):
        """The root logical volume when the preview's root is LVM (CMP-154)."""
        if found := layout.activate_root(self.runner, device):
            self.group, device = found
        return device

    def close_root(self):
        """Close the root stack after reading the record: the group, then LUKS."""
        if self.group:
            layout.deactivate(self.runner.run, self.group)
            self.group = None
        if self.opened:
            self.runner.run(['cryptsetup', 'close', SOURCE_MAP])
            self.opened = False

    def detach(self):
        if self.mount and self.mount.is_mount():
            subprocess.run(['umount', '-R', str(self.mount)], capture_output=True)
        # udev may have activated the preview's volume group by itself when nbd showed it.
        exposed = (self.nbd + 'p', '/dev/mapper/' + SOURCE_MAP) if self.nbd else ('/dev/mapper/' + SOURCE_MAP,)
        for group in dict.fromkeys([g for g in (self.group, *groups_on(exposed)) if g]):
            subprocess.run(['vgchange', '--activate', 'n', group], capture_output=True)
        self.group = None
        if self.opened:
            subprocess.run(['cryptsetup', 'close', SOURCE_MAP], capture_output=True)
            self.opened = False
        if self.nbd:
            server = nbd_server(self.nbd)
            subprocess.run(['qemu-nbd', '--disconnect', self.nbd], capture_output=True)
            # The server exits after the disconnect, not with it. Until then it holds the
            # preview open: promote would find the partition busy, a revert its medium.
            deadline = time.monotonic() + 30
            while server and Path(f'/proc/{server}').exists() and time.monotonic() < deadline:
                time.sleep(0.2)
            self.nbd = None
        if self.scratch:
            shutil.rmtree(self.scratch, ignore_errors=True)
            self.scratch = None


def groups_on(prefixes):
    """Active LVM volume groups whose physical volumes are on devices with these prefixes."""
    try:
        out = subprocess.run(['pvs', '--noheadings', '-o', 'pv_name,vg_name'], capture_output=True, text=True,
                             timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [fields[1] for fields in (line.split() for line in out.splitlines())
            if len(fields) == 2 and fields[0].startswith(prefixes) and layout.GROUP_NAME.fullmatch(fields[1])]


def mount_source_root(runner, device, point):
    """Read-only mount of the preview's root; a journal replays into the overlay first.
    What still refuses to mount is damaged: the user gets a way out, the log the details."""
    try:
        runner.run(['mount', '-o', SOURCE_MOUNT, device, str(point)])
    except ValidationError as exc:
        raise ValidationError(UNREADABLE) from exc


def source_plan(runner, plan, root_device):
    """The plan as the preview was really built: its root subvolumes are read from the
    disk, so a flat btrfs root from an earlier installer is finished as it is."""
    fstype = runner.run(['blkid', '-s', 'TYPE', '-o', 'value', root_device]).strip()
    try:
        return replace(plan, subvolumes=layout.existing_subvolumes(runner, root_device, fstype))
    except ValidationError as exc:
        raise ValidationError(UNREADABLE) from exc


def mount_source(runner, plan, device, point):
    """mount_source_root for a root with subvolumes (CMP-153): each read-only in place."""
    try:
        layout.mount_root(runner, plan, device, point, SOURCE_MOUNT)
    except ValidationError as exc:
        raise ValidationError(UNREADABLE) from exc


def read_record(runner, root_device, mount, plan=None):
    if plan and plan.subvolumes:
        mount_source(runner, replace(plan, subvolumes=plan.subvolumes[:1]), root_device, mount)
    else:
        mount_source_root(runner, root_device, mount)
    try:
        return json.loads((mount / 'var/lib/agi-os/installation.json').read_text())
    finally:
        runner.run(['umount', str(mount)])


def check_record(record, config, firmware, encrypted, lvm=False):
    installed = Configuration.parse({**record['configuration'], 'disk': config.disk})
    if installed.digest() != config.digest():
        raise ValidationError('The preview holds a different configuration than the one you confirmed')
    if record['firmware'] != firmware:
        raise ValidationError('The preview was installed for a different boot type than this computer')
    if bool(record.get('encrypted')) != encrypted:
        raise ValidationError('The encryption state does not match the installation record')
    if lvm != config.lvm:
        raise ValidationError('The LVM layout of the preview does not match the installation record')


def prepare_table(runner, layout_name, disk, table='gpt'):
    """The target's partition table before the copy: a fresh GPT (or MBR for an msdos
    plan) for "erase"; for "alongside" the existing GPT (backed up first). A brand-new
    disk has no table at all: with nothing on it to keep, it gets an empty GPT instead
    of an error."""
    target = disk['path']
    if layout_name == 'erase':
        layout.wipe_table(runner, target)
        if table == 'msdos':
            runner.run(['sfdisk', '--wipe', 'always', target], input_text='label: dos\n')
        else:
            runner.run(['sgdisk', '--clear', target])
        return
    if not disk.get('pttype'):
        if disk.get('fstype') or not storage_worker.looks_blank(target):
            raise ValidationError('The disk has data but no partition table: installing alongside it is not possible. '
                                  'Choose “Erase the disk” if you don’t need that data.')
        if table == 'msdos':
            runner.run(['sfdisk', '--wipe', 'always', target], input_text='label: dos\n')
        else:
            runner.run(['sgdisk', '--clear', target])
    if table == 'msdos':
        # The MBR and its entries, restorable with sfdisk DISK < file.
        (BACKUPS / f'agi-final-{Path(target).name}.sfdisk').write_text(runner.run(['sfdisk', '--dump', target]))
        return
    try:
        runner.run(['sgdisk', f'--backup=/run/agi-final-{Path(target).name}.gpt', target])
    except ValidationError as exc:
        # Another system's table that sgdisk cannot read cleanly (e.g. a damaged main GPT
        # with an intact backup) is not repaired behind the user's back.
        detail = next((l.strip() for l in str(exc).splitlines() if l.strip()), '')
        raise ValidationError(f'The partition table of {target} could not be read cleanly ({detail[:200]}). '
                              'Nothing was changed. Check it with “sudo sgdisk -v ' + target + '” or repair it in '
                              'the other system first, or choose “Erase the disk”.') from exc


TABLES = {'gpt': 'gpt', 'dos': 'msdos'}


def check_table(plan, disk, layout_name):
    """Next to other systems the disk keeps its table type: the plan must match it."""
    if plan.table == 'msdos':
        layout.check_mbr_size(disk['size'])
    existing = TABLES.get(disk.get('pttype')) if disk.get('pttype') else None
    if layout_name != 'alongside' or existing in (None, plan.table):
        return
    if existing == 'msdos':
        raise ValidationError('This disk has an MBR (msdos) partition table: to install next to its systems, ask the '
                              'agent for partition_table msdos (BIOS with GRUB) and build the preview again. Nothing was changed.')
    raise ValidationError('This disk has a GPT: a system with an MBR (msdos) table can only erase it. '
                          'Choose “Erase the disk” or ask the agent for GPT. Nothing was changed.')


def mbr_slots(runner, target):
    """Free primary entries of the disk's MBR (logical partitions are not created)."""
    table = run_json(runner, ['sfdisk', '--json', target])['partitiontable']
    used = {int(p['node'][len(target):].lstrip('p')) for p in table.get('partitions', [])}
    return 4 - len(used & {1, 2, 3, 4})


def free_regions(runner, disk_path, size):
    table = run_json(runner, ['sfdisk', '--json', disk_path])['partitiontable']
    total = size // SECTOR
    if table.get('label') == 'dos':
        # MBR sectors are 32-bit; the first partition starts after GRUB's 1 MiB gap.
        first, last = ALIGN, min(total, layout.MBR_SECTORS) - 1
    elif table.get('label') != 'gpt':
        raise ValidationError('Installing alongside other systems needs a GPT disk')
    else:
        first, last = int(table.get('firstlba', 2048)), int(table.get('lastlba', total - 34))
    used = sorted((int(p['start']), int(p['start']) + int(p['size']) - 1) for p in table.get('partitions', []))
    regions, cursor = [], first
    for start, end in used:
        if start - cursor >= 2 * ALIGN:
            regions.append((cursor, start - 1))
        cursor = max(cursor, end + 1)
    if last - cursor >= 2 * ALIGN:
        regions.append((cursor, last))
    return [((s + ALIGN - 1) // ALIGN * ALIGN, (e + 1) // ALIGN * ALIGN - 1) for s, e in regions]


def windows_guard(disk, layout_name, enroll):
    """Windows next to the new system must be in a state that survives it (CMP-151). A
    hibernated Windows (Fast Startup included) resumes with a stale view of the disk, so
    installing alongside it is refused before anything is written. BitLocker measures the
    Secure Boot keys: enrolling new ones would make Windows ask for its recovery key."""
    warnings = []
    if layout_name != 'alongside':
        return warnings
    for part in disk['partitions']:
        if part.get('fstype') == 'ntfs' and not part['mounted']:
            state = storage_worker.hibernated(part)
            if state is None:
                raise ValidationError(f'Windows on {part["path"]} could not be checked, so nothing was installed. '
                                      'Start Windows, run “chkdsk /f”, shut it down fully and try again.')
            if state:
                raise ValidationError(f'Windows on {part["path"]} is hibernated or was shut down with Fast Startup; '
                                      'installing next to it now could corrupt it. Start Windows, turn off Fast Startup, '
                                      'hold Shift while you click Shut down, and try again. Nothing was changed.')
        if part.get('fstype') == 'BitLocker':
            if enroll:
                raise ValidationError('Windows on this disk uses BitLocker: enrolling Secure Boot keys would make it ask '
                                      'for the recovery key at every start. Install without enrolling the keys; after '
                                      'suspending BitLocker in Windows you can enroll them with sudo sbctl enroll-keys --microsoft.')
            if BITLOCKER_NOTE not in warnings:
                warnings.append(BITLOCKER_NOTE)
    return warnings


def existing_esp(runner, disk):
    """The EFI system partition already on the target (Windows' or another system's), or None."""
    if disk.get('pttype') != 'gpt':
        return None
    table = run_json(runner, ['sfdisk', '--json', disk['path']])['partitiontable']
    return next((p['node'] for p in table.get('partitions', [])
                 if str(p.get('type', '')).upper() == layout.ESP_GUID), None)


def inspect_esp(runner, node, point):
    """Free bytes on an existing ESP and whether Windows Boot Manager lives there; read-only."""
    point.mkdir(exist_ok=True)
    runner.run(['mount', '-o', SOURCE_MOUNT, node, str(point)])
    try:
        stat = os.statvfs(point)
        return stat.f_bavail * stat.f_frsize, (point / WINDOWS_LOADER).is_file()
    finally:
        runner.run(['umount', str(point)])


def kept_partitions(runner, target, skip=()):
    """Identity of every partition of other systems on the target: it must not change."""
    table = run_json(runner, ['sfdisk', '--json', target])['partitiontable']
    return {(int(p['start']), int(p['size']), str(p.get('type', '')).upper(), str(p.get('uuid', '')).upper())
            for p in table.get('partitions', []) if p['node'] not in skip}


def windows_entry(esp_uuid):
    """A GRUB menu entry that chainloads Windows Boot Manager from its own ESP."""
    return ('#!/bin/sh\nexec tail -n +3 "$0"\n'
            "menuentry 'Windows Boot Manager' --class windows --class os {\n"
            '    insmod part_gpt\n    insmod fat\n'
            f'    search --no-floppy --fs-uuid --set=root {esp_uuid}\n'
            f'    chainloader /{WINDOWS_LOADER}\n}}\n')


def bios_windows(disk):
    """The NTFS partition of a BIOS Windows on this MBR disk (the one holding its boot
    manager), or None. Read through a temporary read-only mount."""
    if disk.get('pttype') != 'dos':
        return None
    for part in disk.get('partitions', []):
        if part.get('fstype') != 'ntfs' or part.get('mounted'):
            continue
        point = storage_worker.PREVIEW / 'check'
        if not storage_worker.read_only_mount(part['path'], 'ntfs', point):
            continue
        try:
            if any((point / name).is_file() for name in ('bootmgr', 'BOOTMGR')):
                return part
        finally:
            subprocess.run(['umount', str(point)], capture_output=True, timeout=60)
    return None


def bios_windows_entry(uuid):
    """A GRUB menu entry that starts a BIOS Windows through its partition's boot sector."""
    return ('#!/bin/sh\nexec tail -n +3 "$0"\n'
            "menuentry 'Windows' --class windows --class os {\n"
            '    insmod part_msdos\n    insmod ntfs\n'
            f'    search --no-floppy --fs-uuid --set=root {uuid}\n'
            '    chainloader +1\n}\n')


def promote(runner, request, disk, source, plan):
    """Turn the nested partitions of the preview partition into real disk partitions."""
    target = disk['path']
    firmware = plan.firmware
    preview = request['image']['path']
    table = run_json(runner, ['sfdisk', '--json', target])['partitiontable']
    entry = next((p for p in table['partitions'] if p['node'] == preview), None)
    if entry is None or entry.get('name') != 'AGIOS-PREVIEW':
        raise ValidationError('The preview partition is not on the target disk')
    base, number = int(entry['start']), int(preview[len(target):].lstrip('p'))
    nested = sorted(source.partitions, key=lambda p: int(p['start']))
    for part in nested:
        if int(part['start']) % ALIGN:
            raise ValidationError('The preview partitions are not aligned; they can’t be promoted')
    if plan.table == 'msdos':
        return promote_mbr(runner, request, disk, source, plan, base, nested)
    emit('final-progress', text='Promoting the preview partitions to disk partitions (no data moves)')
    runner.run(['sgdisk', f'--backup=/run/agi-final-{Path(target).name}.gpt', target])
    if request['layout'] == 'erase':
        others = [int(p['node'][len(target):].lstrip('p')) for p in table['partitions'] if p['node'] != preview]
        args = ['sgdisk', *[f'--delete={n}' for n in others], target]
        if others:
            runner.run(args)
    args = ['sgdisk', f'--delete={number}']
    kinds = {}
    for index, part in enumerate(nested):
        start, end = base + int(part['start']), base + int(part['start']) + int(part['size']) - 1
        name = part.get('name', '')
        kind = 'bios' if name == 'BIOS' else 'boot' if name == 'AGI-BOOT' else 'linux'
        typecode = plan.part('boot').typecode if kind == 'boot' else TYPES[kind]
        args += [f'--new=0:{start}:{end}', f'--typecode=0:{typecode}', f'--change-name=0:{name or "AGI-ROOT"}']
        kinds[kind] = (start, end)
    runner.run(args + [target])
    # Erase the nested table signatures and the preview record now sitting in gaps between
    # real partitions: everything before the first nested partition (aligned, so >= 2048).
    head = min(int(p['start']) for p in nested)
    runner.run(['dd', 'if=/dev/zero', f'of={target}', 'bs=512', f'seek={base}', f'count={head}', 'conv=notrunc,fsync'])
    tail = base + int(entry['size']) - 33
    runner.run(['dd', 'if=/dev/zero', f'of={target}', 'bs=512', f'seek={tail}', 'count=33', 'conv=notrunc,fsync'])
    runner.run(['partprobe', target])
    runner.run(['udevadm', 'settle', '--timeout=30'])
    refreshed = run_json(runner, ['sfdisk', '--json', target])['partitiontable']['partitions']
    def node(kind):
        start = kinds[kind][0]
        return next(p['node'] for p in refreshed if int(p['start']) == start)
    return node('boot'), node('linux'), False


def promote_mbr(runner, request, disk, source, plan, base, nested):
    """The preview's MBR entries become the disk's new MBR at the same absolute sectors.
    The disk's own table was a GPT holding the preview partition; only a whole-disk
    install converts it (next to other systems the disk keeps its table type)."""
    target = disk['path']
    if request['layout'] != 'erase' or source.label != 'dos':
        raise ValidationError('An MBR (msdos) system is installed only on a whole disk; nothing was changed')
    roles = {p.number: p.role for p in plan.partitions}
    absolute = []
    for part in nested:
        start, size = base + int(part['start']), int(part['size'])
        if start + size > layout.MBR_SECTORS:
            raise ValidationError('An MBR (msdos) table covers only the first 2 TiB of the disk; choose GPT')
        role = roles.get(int(part['node'][len(source.device):].lstrip('p')))
        if role is None:
            raise ValidationError('The preview holds an unexpected partition')
        absolute.append((role, start, size))
    emit('final-progress', text='Promoting the preview partitions to an MBR partition table (no data moves)')
    runner.run(['sgdisk', f'--backup=/run/agi-final-{Path(target).name}.gpt', target])
    runner.run(['sgdisk', '--zap-all', target])
    # The new entries lie over the preview's file systems: sfdisk must not wipe them.
    runner.run(['sfdisk', '--wipe', 'always', '--wipe-partitions', 'never', '--label', 'dos', target],
               input_text=layout.mbr_script([(start, size, layout.MBR_LINUX, role == 'boot')
                                             for role, start, size in absolute]))
    # The preview's own MBR sits in the gap before its first partition now.
    head = min(int(p['start']) for p in nested)
    runner.run(['dd', 'if=/dev/zero', f'of={target}', 'bs=512', f'seek={base}', f'count={head}', 'conv=notrunc,fsync'])
    runner.run(['partprobe', target])
    runner.run(['udevadm', 'settle', '--timeout=30'])
    refreshed = run_json(runner, ['sfdisk', '--json', target])['partitiontable']['partitions']
    def node(role):
        start = next(s for r, s, _ in absolute if r == role)
        return next(p['node'] for p in refreshed if int(p['start']) == start)
    return node('boot'), node('root'), False


def gpt_partitions(runner, plan, target, start, end):
    """The plan's GPT entries in the free region start..end; returns where /boot starts and ends."""
    args = ['sgdisk']
    if plan.firmware == 'bios':
        bios = plan.part('bios')
        args += [f'--new=0:{start}:{start + 4095}', f'--typecode=0:{bios.typecode}', f'--change-name=0:{bios.name}']
        start += 4096
    boot_part, root_part = plan.part('boot'), plan.part('root')
    boot_end = start + boot_part.size // SECTOR - 1
    args += [f'--new=0:{start}:{boot_end}', f'--typecode=0:{boot_part.typecode}', f'--change-name=0:{boot_part.name}',
             f'--new=0:{boot_end + 1}:{end}', f'--typecode=0:{root_part.typecode}', f'--change-name=0:{root_part.name}', target]
    runner.run(args)
    return start, boot_end


def copy(runner, request, disk, source, plan, passphrase, mount, skip=(), reserve=0):
    """Create fresh partitions on the target and copy the preview into them file by file.

    Paths in skip (root-relative, e.g. the hibernation swap file) are recreated by the
    caller: a copied swap file would sit at other physical blocks than resume_offset says.
    reserve is the space the caller needs for them on the new root."""
    target = disk['path']
    check_table(plan, disk, request['layout'])  # finalize() checked it already; a GPT write would convert an MBR.
    if plan.table == 'msdos' and request['layout'] == 'alongside' and disk.get('pttype') and mbr_slots(runner, target) < 2:
        raise ValidationError('The MBR of this disk has fewer than two free primary entries for /boot and the root '
                              '(an MBR holds four). Nothing was changed.')
    boot_number = plan.part('boot').number
    src_root, encrypted = source.open_root(plan.part('root').number, passphrase)
    src_mount = mount / 'source'
    src_mount.mkdir()
    # The preview's subvolumes (CMP-153) are mounted in place, so rsync copies each into
    # the same subvolume of the new root.
    plan = source_plan(runner, plan, src_root)
    mount_source(runner, plan, src_root, src_mount)
    source.mount = src_mount
    runner.run(['mount', '-o', SOURCE_MOUNT, source.partition(boot_number), str(src_mount / 'boot')])
    skipped = [f'--exclude={src_mount / path}' for path in skip]
    # Not -x: subvolumes are other file systems to du; /boot and snapshots are left out here.
    used = (int(runner.run(['du', '-sB1', *skipped, f'--exclude={src_mount / "boot"}', f'--exclude={src_mount / ".snapshots"}',
                            str(src_mount)]).split()[0])
            + int(runner.run(['du', '-sB1', str(src_mount / 'boot')]).split()[0]))
    needed = used + used // 5 + 2 * GIB + reserve
    emit('final-progress', text=f'Creating partitions on {target} for {used / GIB:.1f} GiB of data')
    prepare_table(runner, request['layout'], disk, plan.table)
    regions = [r for r in free_regions(runner, target, disk['size']) if (r[1] - r[0] + 1) * SECTOR >= needed]
    if not regions:
        raise ValidationError(f'The disk has no free space for the system ({needed / GIB:.1f} GiB)')
    start, end = max(regions, key=lambda r: r[1] - r[0])
    if plan.table == 'msdos':
        boot_part, root_part = plan.part('boot'), plan.part('root')
        boot_end = start + boot_part.size // SECTOR - 1
        # Active flag only on a disk of its own: next to Windows its partition stays the active one.
        runner.run(['sfdisk', '--append', '--wipe-partitions', 'never', target], input_text=layout.mbr_script(
            [(start, boot_part.size // SECTOR, boot_part.typecode, request['layout'] == 'erase'),
             (boot_end + 1, end - boot_end, root_part.typecode, False)]))
    else:
        start, boot_end = gpt_partitions(runner, plan, target, start, end)
    runner.run(['partprobe', target])
    runner.run(['udevadm', 'settle', '--timeout=30'])
    refreshed = run_json(runner, ['sfdisk', '--json', target])['partitiontable']['partitions']
    boot = next(p['node'] for p in refreshed if int(p['start']) == start)
    root_partition = next(p['node'] for p in refreshed if int(p['start']) == boot_end + 1)
    fstype = runner.run(['blkid', '-s', 'TYPE', '-o', 'value', src_root]).strip()
    layout.format_boot(runner, plan, boot)
    if encrypted:
        emit('final-progress', text='Encrypting the root partition of the target disk (LUKS2)')
    # The preview's file system decides, not the plan's: they match unless the record was forged.
    target_plan = replace(plan, encrypted=encrypted, filesystem=fstype,
                          group=plan.group if getattr(source, 'group', None) else None)
    root = layout.create_root(runner, target_plan, root_partition, passphrase, TARGET_MAP)
    dst = mount / 'target'
    dst.mkdir()
    layout.mount_root(runner, target_plan, root, dst)
    layout.mount_boot(runner, target_plan, boot, dst)
    emit('final-progress', text='Copying the checked system file by file', step='copy', percent=0)
    # Snapshots of the preview's root are not part of the installed system.
    excludes = ['--exclude=/boot/*', '--exclude=/.snapshots/*', *[f'--exclude=/{path}' for path in skip]]
    # --no-inc-recursive: rsync counts all files first, so its overall percentage is steady.
    runner.run(['rsync', '-aHAX', '--numeric-ids', '--info=progress2', '--no-inc-recursive', *excludes, f'{src_mount}/', f'{dst}/'],
               timeout=14400, progress=copy_progress('Copying the checked system file by file'))
    # The boot partition is FAT on UEFI: copy contents without POSIX ownership or modes.
    runner.run(['rsync', '-rt', '--no-perms', '--no-owner', '--no-group', '--modify-window=2', f'{src_mount}/boot/', f'{dst}/boot/'], timeout=3600)
    emit('final-progress', text='Verifying the copy by checksums')
    differences = runner.run(['rsync', '-aHAXcn', '--numeric-ids', *excludes, '--out-format=%n', f'{src_mount}/', f'{dst}/'], timeout=14400).strip()
    differences += runner.run(['rsync', '-rcn', '--no-perms', '--no-owner', '--no-group', '--out-format=%n', f'{src_mount}/boot/', f'{dst}/boot/'], timeout=3600).strip()
    if differences:
        raise ValidationError('The copy did not pass the check: ' + differences.splitlines()[0])
    runner.run(['umount', '--recursive', str(src_mount)])
    source.mount = None
    return boot, root_partition, root, encrypted, dst


def copy_progress(text):
    """The overall percentage rsync --info=progress2 prints, as a final-progress event for
    each new whole percent (the site shows the longest step of the copy moving)."""
    last = [0]

    def output(chunk):
        found = re.findall(r'(\d{1,3})%', chunk)
        percent = min(100, int(found[-1])) if found else last[0]
        if percent > last[0]:
            last[0] = percent
            emit('final-progress', text=f'{text}: {percent}%', step='copy', percent=percent)
    return output


def discard_hibernation_image(runner, dst):
    """A preview hibernated instead of shut down keeps its memory image in the swap file.
    Promoted as is, the new system would resume that image over a file system the
    finalization has changed. The swap header is rewritten in place (same blocks, so
    resume_offset stays valid) and the first boot starts fresh."""
    path = dst / SWAPFILE
    try:
        with open(path, 'rb') as handle:
            header = handle.read(PAGE)
    except OSError:
        return False
    if len(header) < PAGE or not header[-10:].startswith(HIBERNATION_SIGNATURES):
        return False
    emit('final-progress', text='The preview was hibernated, not shut down: its saved session is discarded '
         'so the installed system starts fresh')
    runner.run(['mkswap', str(path)])
    return True


def swapfile_size(record):
    """Sized for this computer's RAM (the preview was sized for the same inventory)."""
    try:
        return hibernation_swap_size(inventory()['hardware'].get('memory'))
    except ValidationError:
        return int(record['hibernation']['size'])


def recreate_swapfile(runner, dst, root_uuid, record, size):
    """The hibernation swap file on the new root filesystem: new UUID, new offset."""
    fstype = runner.run(['findmnt', '-n', '-o', 'FSTYPE', str(dst)]).strip()
    emit('final-progress', text=f'Creating the hibernation swap file ({size // 2**30} GiB) on the target disk')
    offset = create_swapfile(runner, dst, fstype, size)
    record['hibernation'] = {**record['hibernation'], 'size': size, 'resume_uuid': root_uuid, 'resume_offset': offset}
    return resume_parameter(root_uuid, offset)


def missing_drivers(hardware, config, installed):
    """Driver plan for the real hardware and the part of it absent from the installed system."""
    plan = driver_plan(hardware, config.packages, config.session)
    return plan, [p for p in plan['packages'] if p not in installed]


def fit_drivers(runner, chroot, dst, config, record, encrypted):
    """Complete the drivers for the computer Live runs on. The disk is already written
    here, so nothing in this step may fail the finalization: every problem becomes a
    warning that the page, the record and agi-os-verify show. The system still boots
    with the kernel's own drivers."""
    warnings, plan, missing = [], None, []
    try:
        hardware = profile(inventory()['hardware'])
        installed = set(runner.run([*chroot, 'pacman', '-Qq']).splitlines())
        plan, missing = missing_drivers(hardware, config, installed)
        # Recorded before installing: agi-os-verify then checks the real computer's plan,
        # so a failed top-up stays visible until the user installs the drivers.
        record['hardware'], record['drivers'] = hardware, plan
        if missing:
            emit('final-progress', text='Adding the drivers for this computer’s hardware: ' + ', '.join(missing))
            free = int(runner.run(['df', '--output=avail', '-B1', str(dst)]).split()[-1])
            if free < 2 * GIB:
                raise ValidationError('less than 2 GiB is free on the disk')
            # The target has no sync database (the preview dropped its cache); a plain
            # -Sy would be a partial upgrade, so the whole system is brought to one repository state.
            runner.run([*chroot, 'pacman', '-Syu', '--noconfirm', '--needed', '--', *missing], timeout=3600)
            runner.run([*chroot, 'pacman', '-Scc', '--noconfirm'])
            record['packages'] = list(dict.fromkeys([*record.get('packages', []), *missing]))
        else:
            emit('final-progress', text='The drivers for this computer’s hardware are already installed in the preview: '
                 + (', '.join(plan['packages']) or 'no extra ones needed'))
        # The initramfs drop-in always follows the final plan (mkinitcpio -P runs next).
        dropin = dst / 'etc/mkinitcpio.conf.d/agi-os.conf'
        if initramfs := initramfs_config(plan, encrypted, bool(record.get('hibernation')), config.lvm):
            dropin.parent.mkdir(exist_ok=True)
            dropin.write_text(initramfs)
        elif dropin.exists():
            dropin.unlink()
        for service in plan['services']:
            try:
                runner.run([*chroot, 'systemctl', 'enable', service])
            except ValidationError:
                warnings.append(f'Service {service} is not enabled. After you log in, run: sudo systemctl enable --now {service}')
    except Cancelled:
        raise
    except Exception as exc:
        lines = [l for l in str(exc).splitlines() if l.strip()]
        reason = next((l for l in reversed(lines) if l.startswith('error:')), lines[0] if lines else type(exc).__name__)
        warnings.append('Could not add the drivers' + (' ' + ', '.join(missing) if missing else '') + ' — ' + reason[:300]
                        + '. The system boots with the kernel’s basic drivers'
                        + ('; after you log in, run: sudo pacman -Syu ' + ' '.join(missing) if missing else ''))
    for warning in warnings:
        emit('final-warning', text=warning)
    record['warnings'] = record.get('warnings', []) + warnings
    return plan, missing


def check_signatures(runner, chroot, record):
    """Root `sbctl verify` of the final disk, kept in the record: after a copy the ESP may be
    unreadable to the user, and agi-os-verify then relies on this result."""
    emit('final-progress', text='Checking the bootloader and kernel signatures (Secure Boot)')
    unsigned = sbctl_unsigned(runner.run([*chroot, 'sbctl', 'verify']))
    record['secure_boot']['verified'] = not unsigned
    return unsigned


def enroll_keys(runner, chroot, record):
    """Write this system's own Secure Boot keys into the firmware, keeping Microsoft's
    certificates: option ROMs of graphics cards and other systems still need them."""
    if not (record.get('secure_boot') or {}).get('signed'):
        raise ValidationError('The system in the preview is not signed for Secure Boot; the keys were not enrolled')
    unsigned = check_signatures(runner, chroot, record)
    if unsigned:
        raise ValidationError('Not signed for Secure Boot: ' + ', '.join(unsigned) + '. The keys were not enrolled')
    emit('final-progress', text='Enrolling this system’s Secure Boot keys in the firmware (together with Microsoft’s keys)')
    runner.run([*chroot, 'sbctl', 'enroll-keys', '--microsoft'])
    record['secure_boot']['enrolled'] = True


def enroll_or_warn(runner, chroot, record):
    """The system is already on the disk and boots (Setup Mode enforces nothing): a
    failed enrollment is a warning with the command to finish it later, not a failure."""
    try:
        enroll_keys(runner, chroot, record)
    except Cancelled:
        raise
    except Exception as exc:
        lines = [l for l in str(exc).splitlines() if l.strip()]
        warning = ('Secure Boot keys were not enrolled — ' + (lines[-1] if lines else type(exc).__name__)[:300]
                   + '. The system is signed and boots; to turn on Secure Boot, log in and run: '
                   'sudo sbctl enroll-keys --microsoft, then turn on Secure Boot in the UEFI settings')
        record['warnings'] = record.get('warnings', []) + [warning]
        emit('final-warning', text=warning)


def live_firmware():
    return 'uefi' if Path('/sys/firmware/efi').is_dir() else 'bios'


def finalize(request, runner):
    config, disk = checked_request(request)
    target = config.disk
    firmware = live_firmware()
    plan = layout.plan_for(config, firmware)
    check_table(plan, disk, request['layout'])
    passphrase = request.pop('passphrase')
    mount = Path(tempfile.mkdtemp(prefix='agi-final-', dir='/mnt'))
    source = Source(runner, request['image'])
    opened_target = False
    target_group = None
    dst = None
    efi_mounted = False
    try:
        # Before the preview is even opened: nothing is written while Windows is not safe.
        notes = windows_guard(disk, request['layout'], request['enroll_keys'])
        emit('final-progress', text='Opening the preview for checking')
        source.attach()
        src_root, encrypted = source.open_root(plan.part('root').number, passphrase)
        plan = source_plan(runner, plan, src_root)
        record = read_record(runner, src_root, mount, plan)
        check_record(record, config, firmware, encrypted, bool(source.group))
        source.close_root()
        esp, windows = None, False
        if request['layout'] == 'alongside' and firmware == 'uefi':
            esp = existing_esp(runner, disk)
        if esp:
            free, windows = inspect_esp(runner, esp, mount / 'esp')
            if config.bootloader == 'systemd-boot':
                if free < ESP_ROOM:
                    raise ValidationError(f'The EFI system partition {esp} has only {free // MIB} MiB free; systemd-boot '
                                          f'needs {ESP_ROOM // MIB} MiB there. Nothing was changed.')
                plan = replace(layout.plan_for(config, firmware, shared_esp=True), subvolumes=plan.subvolumes)
        preview = request['image']['path'] if request['image']['on_target'] else None
        kept = kept_partitions(runner, target, {preview}) if request['layout'] == 'alongside' and disk.get('pttype') else None
        if request['image']['on_target']:
            source.detach()
            boot, root_partition, _ = promote(runner, request, disk, source, plan)
            root = root_partition
            if encrypted:
                runner.run(['cryptsetup', 'open', '--key-file', '-', root_partition, TARGET_MAP], input_text=passphrase)
                opened_target = True
                root = '/dev/mapper/' + TARGET_MAP
            # A promoted LVM root keeps the preview's volume group (same name, same UUIDs).
            if found := layout.activate_root(runner, root):
                target_group, root = found
            dst = mount / 'target'
            dst.mkdir()
            layout.mount_root(runner, plan, root, dst)
            runner.run(['mount', boot, str(dst / 'boot')])
            if record.get('hibernation'):
                discard_hibernation_image(runner, dst)
            moved = False
        else:
            # The swap directory (a subvolume on btrfs) is recreated, not copied.
            skip = [str(Path(SWAPFILE).parent)] if record.get('hibernation') else []
            swap_size = swapfile_size(record) if skip else 0
            target_group = plan.group  # created by the copy; deactivated even if the copy fails
            boot, root_partition, root, encrypted, dst = copy(runner, request, disk, source, plan, passphrase, mount,
                                                              skip, swap_size)
            opened_target = encrypted
            moved = True
        passphrase = None
        chroot = ['arch-chroot', str(dst)]
        if plan.shared_esp:
            emit('final-progress', text=f'Sharing the EFI system partition {esp} with the other system (not formatted)')
            (dst / 'efi').mkdir(exist_ok=True)
            runner.run(['mount', '-o', 'umask=0077', esp, str(dst / 'efi')])
            efi_mounted = True
            if not moved:
                # genfstab runs only after a copy; a promoted system keeps its fstab and gains /efi.
                esp_uuid = runner.run(['blkid', '-s', 'UUID', '-o', 'value', esp]).strip()
                with open(dst / 'etc/fstab', 'a') as fstab:
                    fstab.write(f'UUID={esp_uuid} /efi vfat umask=0077 0 2\n')
        if moved:
            emit('final-progress', text='Updating partition IDs in the new system')
            root_uuid = runner.run(['blkid', '-s', 'UUID', '-o', 'value', root]).strip()
            luks_uuid = runner.run(['blkid', '-s', 'UUID', '-o', 'value', root_partition]).strip() if encrypted else None
            resume = None
            if record.get('hibernation'):
                resume = recreate_swapfile(runner, dst, root_uuid, record, swap_size)
            (dst / 'etc/fstab').write_text(layout.fstab(runner.run(['genfstab', '-U', str(dst)])) + (swap_fstab_line() if resume else ''))
            options = boot_options(root_uuid, luks_uuid, resume, layout.root_flags(plan), bool(target_group))
            defaults = dst / 'etc/default/grub'
            if defaults.exists() and (encrypted or resume):
                defaults.write_text(grub_defaults(defaults.read_text(), luks_uuid, resume))
            for entry in (dst / 'boot/loader/entries').glob('*.conf') if (dst / 'boot/loader/entries').is_dir() else []:
                text = '\n'.join(('options ' + options) if line.startswith('options ') else line for line in entry.read_text().splitlines())
                entry.write_text(text + '\n')
            record['root_uuid'] = root_uuid
        fit_drivers(runner, chroot, dst, config, record, encrypted)
        emit('final-progress', text='Rebuilding initramfs for this computer’s hardware')
        runner.run([*chroot, 'mkinitcpio', '-P'])
        emit('final-progress', text='Registering the boot of the installed system')
        if config.bootloader == 'systemd-boot' and plan.shared_esp:
            # systemd-boot reads loader.conf only from the ESP; kernels and entries stay on
            # the XBOOTLDR /boot, and Windows Boot Manager on the ESP gets its menu entry.
            conf = dst / 'efi/loader/loader.conf'
            if not conf.exists():
                conf.parent.mkdir(parents=True, exist_ok=True)
                own = dst / 'boot/loader/loader.conf'
                conf.write_text(own.read_text() if own.is_file() else 'default agi-os.conf\ntimeout 3\n')
            with preserve_efi_fallback(dst / 'efi'):
                runner.run([*chroot, 'bootctl', '--esp-path=/efi', '--boot-path=/boot', 'install'])
            # The automatic boot-time updater also overwrites the ESP fallback.
            # AGIOS's own updater refreshes systemd-boot while preserving it.
            runner.run([*chroot, 'systemctl', 'disable', 'systemd-boot-update.service'])
        elif config.bootloader == 'systemd-boot':
            runner.run([*chroot, 'bootctl', '--esp-path=/boot', 'install'])
        elif firmware == 'uefi':
            if windows:
                esp_uuid = runner.run(['blkid', '-s', 'UUID', '-o', 'value', esp]).strip()
                entry = dst / 'etc/grub.d/35_agios_windows'
                entry.parent.mkdir(parents=True, exist_ok=True)
                entry.write_text(windows_entry(esp_uuid))
                entry.chmod(0o755)
            runner.run([*chroot, 'grub-install', '--target=x86_64-efi', '--efi-directory=/boot', '--bootloader-id=AGIOS', '--removable'])
            runner.run([*chroot, 'grub-install', '--target=x86_64-efi', '--efi-directory=/boot', '--bootloader-id=AGIOS'])
            runner.run([*chroot, 'grub-mkconfig', '-o', '/boot/grub/grub.cfg'])
        else:
            windows_part = bios_windows(disk) if request['layout'] == 'alongside' else None
            if windows_part:
                entry = dst / 'etc/grub.d/35_agios_windows'
                entry.parent.mkdir(parents=True, exist_ok=True)
                entry.write_text(bios_windows_entry(runner.run(['blkid', '-s', 'UUID', '-o', 'value', windows_part['path']]).strip()))
                entry.chmod(0o755)
                windows = True
            runner.run([*chroot, 'grub-install', '--target=i386-pc', target])
            runner.run([*chroot, 'grub-mkconfig', '-o', '/boot/grub/grub.cfg'])
        if request['enroll_keys']:
            enroll_or_warn(runner, chroot, record)
        elif (record.get('secure_boot') or {}).get('signed'):
            try:
                unsigned = check_signatures(runner, chroot, record)
            except Cancelled:
                raise
            except Exception as exc:
                record['secure_boot']['verified'] = False
                unsigned = [type(exc).__name__]
            if unsigned:
                warning = 'Secure Boot signatures are not confirmed: ' + ', '.join(unsigned)[:300] + '. Run sudo sbctl verify'
                record['warnings'] = record.get('warnings', []) + [warning]
                emit('final-warning', text=warning)
        if kept is not None and kept - kept_partitions(runner, target):
            raise ValidationError('A partition of another system on the disk changed during the installation. '
                                  'Do not start that system before checking it; the GPT backup is in /run.')
        if esp or windows:
            record['dual_boot'] = {'esp': esp, 'shared_esp': plan.shared_esp, 'windows': windows}
        for note in notes:
            emit('final-warning', text=note)
        record['warnings'] = record.get('warnings', []) + notes
        # A new acceptance ID: the preview's first-boot result must not count for real hardware.
        record['finalization'] = {'preview_id': record['id'], 'target': target, 'mode': 'copy' if moved else 'promote',
                                  'layout': request['layout'], 'target_fingerprint': disk['fingerprint'], 'live_firmware': firmware}
        record['id'] = uuid.uuid4().hex
        record['configuration']['disk'] = target
        record['status'] = 'final_first_boot_pending'
        (dst / 'var/lib/agi-os/installation.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
        runner.run(['sync'])
        if efi_mounted:
            runner.run(['umount', str(dst / 'efi')])
        runner.run(['umount', str(dst / 'boot')])
        runner.run(['umount', '--recursive', str(dst)])
        dst = None
        layout.deactivate(runner.run, target_group)
        target_group = None
        if opened_target:
            runner.run(['cryptsetup', 'close', TARGET_MAP]); opened_target = False
        emit('finalized', text='The system on ' + target + ' is ready to boot. Shut down Live, remove the stick and power on the computer.',
             target=target, record_id=record['id'], mode='copy' if moved else 'promote')
    finally:
        passphrase = None
        request.pop('passphrase', None)
        if dst and dst.exists():
            subprocess.run(['umount', '-R', str(dst)], capture_output=True)
        if target_group:
            subprocess.run(['vgchange', '--activate', 'n', target_group], capture_output=True)
        if opened_target:
            subprocess.run(['cryptsetup', 'close', TARGET_MAP], capture_output=True)
        source.detach()
        for child in ('source', 'target', 'esp'):
            try: (mount / child).rmdir()
            except OSError: pass
        try: mount.rmdir()
        except OSError: pass


def main():
    try:
        with open('/run/agi-os-finalize.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            request = adopt(json.loads(sys.stdin.readline(1000000)))
            LOG.info('finalize.start', 'Finishing the installation', layout=request.get('layout'), target=request.get('target'))
            finalize(request, Runner(LOG))
            LOG.info('finalize.done', 'Installation finished')
    except Exception as exc:
        known = isinstance(exc, ValidationError)
        LOG.error('finalize.failed', str(exc) if known else 'Internal finishing error', exc=None if known else exc)
        emit('final-error', text=str(exc) if known else 'Finishing stopped on an internal error: ' + type(exc).__name__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
