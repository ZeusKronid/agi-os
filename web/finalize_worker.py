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
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from settings import ENGINE
sys.path.insert(0, str(ENGINE))
from domain import SWAPFILE, Configuration, ValidationError, hibernation_swap_size
from hardware import SETUP_MODE_VAR, driver_plan, efi_flag, initramfs_config, profile
from journal import Logger, adopt
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
TYPES = {'bios': 'ef02', 'boot': 'ef00', 'linux': '8300'}
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


def run_json(runner, args):
    return json.loads(runner.run(args))


def checked_request(request):
    if os.geteuid() != 0 or not live_environment():
        raise ValidationError('Finishing the installation is allowed only inside Live')
    if not isinstance(request, dict) or set(request) != {'target', 'fingerprint', 'configuration', 'passphrase', 'image', 'layout', 'confirmation', 'enroll_keys'}:
        raise ValidationError('Unknown finishing request')
    if not isinstance(request['configuration'], dict) or not all(isinstance(request[k], str) for k in ('target', 'fingerprint', 'confirmation')):
        raise ValidationError('Некорректный запрос завершения')
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
        raise ValidationError('Некорректный выбор записи ключей Secure Boot')
    if request['enroll_keys'] and (config.bootloader != 'systemd-boot' or efi_flag(SETUP_MODE_VAR) is not True):
        # Checked before any disk change: the firmware must accept new keys right now.
        raise ValidationError('Прошивка не в режиме Setup Mode: ключи Secure Boot записать нельзя. '
                              'Сотрите ключи в настройках UEFI или снимите отметку записи ключей')
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
            raise ValidationError('Образ превью находится вне подготовленного хранилища')
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
        self.nbd = None
        self.scratch = None
        self.opened = False
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
        if table.get('label') != 'gpt' or not table.get('partitions'):
            raise ValidationError('The preview has no expected partition table')
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
            return '/dev/mapper/' + SOURCE_MAP, True
        return device, False

    def detach(self):
        if self.mount and self.mount.is_mount():
            subprocess.run(['umount', '-R', str(self.mount)], capture_output=True)
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


def mount_source_root(runner, device, point):
    """Read-only mount of the preview's root; a journal replays into the overlay first.
    What still refuses to mount is damaged: the user gets a way out, the log the details."""
    try:
        runner.run(['mount', '-o', SOURCE_MOUNT, device, str(point)])
    except ValidationError as exc:
        raise ValidationError(UNREADABLE) from exc


def read_record(runner, root_device, mount):
    mount_source_root(runner, root_device, mount)
    try:
        return json.loads((mount / 'var/lib/agi-os/installation.json').read_text())
    finally:
        runner.run(['umount', str(mount)])


def check_record(record, config, firmware, encrypted):
    installed = Configuration.parse({**record['configuration'], 'disk': config.disk})
    if installed.digest() != config.digest():
        raise ValidationError('The preview holds a different configuration than the one you confirmed')
    if record['firmware'] != firmware:
        raise ValidationError('The preview was installed for a different boot type than this computer')
    if bool(record.get('encrypted')) != encrypted:
        raise ValidationError('The encryption state does not match the installation record')


def prepare_table(runner, layout, disk):
    """The target's partition table before the copy: a fresh GPT for "erase"; for
    "alongside" the existing GPT (backed up first). A brand-new disk has no table at
    all: with nothing on it to keep, it gets an empty GPT instead of an error."""
    target = disk['path']
    if layout == 'erase':
        runner.run(['sgdisk', '--zap-all', target])
        runner.run(['sgdisk', '--clear', target])
        return
    if not disk.get('pttype'):
        if disk.get('fstype') or not storage_worker.looks_blank(target):
            raise ValidationError('На диске нет таблицы разделов, но есть данные: установка рядом с ними невозможна. '
                                  'Выберите «стереть диск», если эти данные не нужны.')
        runner.run(['sgdisk', '--clear', target])
    runner.run(['sgdisk', f'--backup=/run/agi-final-{Path(target).name}.gpt', target])


def free_regions(runner, disk_path, size):
    table = run_json(runner, ['sfdisk', '--json', disk_path])['partitiontable']
    if table.get('label') != 'gpt':
        raise ValidationError('Installing alongside other systems needs a GPT disk')
    total = size // SECTOR
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


def promote(runner, request, disk, source, firmware):
    """Turn the nested partitions of the preview partition into real disk partitions."""
    target = disk['path']
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
        typecode = TYPES[kind] if not (kind == 'boot' and firmware == 'bios') else TYPES['linux']
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


def copy(runner, request, disk, source, firmware, passphrase, mount, skip=(), reserve=0):
    """Create fresh partitions on the target and copy the preview into them file by file.

    Paths in skip (root-relative, e.g. the hibernation swap file) are recreated by the
    caller: a copied swap file would sit at other physical blocks than resume_offset says.
    reserve is the space the caller needs for them on the new root."""
    target = disk['path']
    boot_number = 1 if firmware == 'uefi' else 2
    root_number = boot_number + 1
    src_root, encrypted = source.open_root(root_number, passphrase)
    src_mount = mount / 'source'
    src_mount.mkdir()
    mount_source_root(runner, src_root, src_mount)
    source.mount = src_mount
    runner.run(['mount', '-o', SOURCE_MOUNT, source.partition(boot_number), str(src_mount / 'boot')])
    skipped = [f'--exclude={src_mount / path}' for path in skip]
    used = int(runner.run(['du', '-sxB1', *skipped, str(src_mount)]).split()[0]) + int(runner.run(['du', '-sB1', str(src_mount / 'boot')]).split()[0])
    needed = used + used // 5 + 2 * GIB + reserve
    emit('final-progress', text=f'Creating partitions on {target} for {used / GIB:.1f} GiB of data')
    prepare_table(runner, request['layout'], disk)
    regions = [r for r in free_regions(runner, target, disk['size']) if (r[1] - r[0] + 1) * SECTOR >= needed]
    if not regions:
        raise ValidationError(f'The disk has no free space for the system ({needed / GIB:.1f} GiB)')
    start, end = max(regions, key=lambda r: r[1] - r[0])
    args = ['sgdisk']
    if firmware == 'bios':
        args += [f'--new=0:{start}:{start + 4095}', '--typecode=0:ef02', '--change-name=0:BIOS']
        start += 4096
    boot_end = start + GIB // SECTOR - 1
    args += [f'--new=0:{start}:{boot_end}', '--typecode=0:' + ('ef00' if firmware == 'uefi' else '8300'), '--change-name=0:AGI-BOOT',
             f'--new=0:{boot_end + 1}:{end}', '--typecode=0:8300', '--change-name=0:AGI-ROOT', target]
    runner.run(args)
    runner.run(['partprobe', target])
    runner.run(['udevadm', 'settle', '--timeout=30'])
    refreshed = run_json(runner, ['sfdisk', '--json', target])['partitiontable']['partitions']
    boot = next(p['node'] for p in refreshed if int(p['start']) == start)
    root_partition = next(p['node'] for p in refreshed if int(p['start']) == boot_end + 1)
    fstype = runner.run(['blkid', '-s', 'TYPE', '-o', 'value', src_root]).strip()
    runner.run(['mkfs.fat', '-F', '32', boot] if firmware == 'uefi' else ['mkfs.ext4', '-F', boot])
    root = root_partition
    if encrypted:
        emit('final-progress', text='Encrypting the root partition of the target disk (LUKS2)')
        runner.run(['cryptsetup', 'luksFormat', '--type', 'luks2', '--batch-mode', '--key-file', '-', root_partition], input_text=passphrase)
        runner.run(['cryptsetup', 'open', '--key-file', '-', root_partition, TARGET_MAP], input_text=passphrase)
        root = '/dev/mapper/' + TARGET_MAP
    force = {'ext4': '-F', 'btrfs': '-f', 'xfs': '-f', 'f2fs': '-f'}[fstype]
    runner.run(['mkfs.' + fstype, force, root])
    dst = mount / 'target'
    dst.mkdir()
    runner.run(['mount', root, str(dst)])
    (dst / 'boot').mkdir()
    runner.run(['mount', boot, str(dst / 'boot')])
    emit('final-progress', text='Copying the checked system file by file')
    excludes = ['--exclude=/boot/*', *[f'--exclude=/{path}' for path in skip]]
    runner.run(['rsync', '-aHAX', '--numeric-ids', *excludes, f'{src_mount}/', f'{dst}/'], timeout=14400)
    # The boot partition is FAT on UEFI: copy contents without POSIX ownership or modes.
    runner.run(['rsync', '-rt', '--no-perms', '--no-owner', '--no-group', '--modify-window=2', f'{src_mount}/boot/', f'{dst}/boot/'], timeout=3600)
    emit('final-progress', text='Verifying the copy by checksums')
    differences = runner.run(['rsync', '-aHAXcn', '--numeric-ids', *excludes, '--out-format=%n', f'{src_mount}/', f'{dst}/'], timeout=14400).strip()
    differences += runner.run(['rsync', '-rcn', '--no-perms', '--no-owner', '--no-group', '--out-format=%n', f'{src_mount}/boot/', f'{dst}/boot/'], timeout=3600).strip()
    if differences:
        raise ValidationError('The copy did not pass the check: ' + differences.splitlines()[0])
    runner.run(['umount', str(src_mount / 'boot')])
    runner.run(['umount', str(src_mount)])
    source.mount = None
    return boot, root_partition, root, encrypted, dst


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
    emit('final-progress', text=f'Создаю swap-файл для гибернации ({size // 2**30} ГиБ) на конечном диске')
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
            emit('final-progress', text='Доустанавливаю драйверы под железо этого компьютера: ' + ', '.join(missing))
            free = int(runner.run(['df', '--output=avail', '-B1', str(dst)]).split()[-1])
            if free < 2 * GIB:
                raise ValidationError('на диске меньше 2 ГиБ свободно')
            # The target has no sync database (the preview dropped its cache); a plain
            # -Sy would be a partial upgrade, so the whole system is brought to one repository state.
            runner.run([*chroot, 'pacman', '-Syu', '--noconfirm', '--needed', '--', *missing], timeout=3600)
            runner.run([*chroot, 'pacman', '-Scc', '--noconfirm'])
            record['packages'] = list(dict.fromkeys([*record.get('packages', []), *missing]))
        else:
            emit('final-progress', text='Драйверы для железа этого компьютера уже установлены в превью: '
                 + (', '.join(plan['packages']) or 'дополнительных не требуется'))
        # The initramfs drop-in always follows the final plan (mkinitcpio -P runs next).
        dropin = dst / 'etc/mkinitcpio.conf.d/agi-os.conf'
        if initramfs := initramfs_config(plan, encrypted, bool(record.get('hibernation'))):
            dropin.parent.mkdir(exist_ok=True)
            dropin.write_text(initramfs)
        elif dropin.exists():
            dropin.unlink()
        for service in plan['services']:
            try:
                runner.run([*chroot, 'systemctl', 'enable', service])
            except ValidationError:
                warnings.append(f'Служба {service} не включена. После входа выполните: sudo systemctl enable --now {service}')
    except Cancelled:
        raise
    except Exception as exc:
        lines = [l for l in str(exc).splitlines() if l.strip()]
        reason = next((l for l in reversed(lines) if l.startswith('error:')), lines[0] if lines else type(exc).__name__)
        warnings.append('Не удалось доустановить драйверы' + (' ' + ', '.join(missing) if missing else '') + ' — ' + reason[:300]
                        + '. Система загрузится с базовыми драйверами ядра'
                        + ('; после входа выполните: sudo pacman -Syu ' + ' '.join(missing) if missing else ''))
    for warning in warnings:
        emit('final-warning', text=warning)
    record['warnings'] = record.get('warnings', []) + warnings
    return plan, missing


def check_signatures(runner, chroot, record):
    """Root `sbctl verify` of the final disk, kept in the record: after a copy the ESP may be
    unreadable to the user, and agi-os-verify then relies on this result."""
    emit('final-progress', text='Проверяю подписи загрузчика и ядра (Secure Boot)')
    unsigned = sbctl_unsigned(runner.run([*chroot, 'sbctl', 'verify']))
    record['secure_boot']['verified'] = not unsigned
    return unsigned


def enroll_keys(runner, chroot, record):
    """Write this system's own Secure Boot keys into the firmware, keeping Microsoft's
    certificates: option ROMs of graphics cards and other systems still need them."""
    if not (record.get('secure_boot') or {}).get('signed'):
        raise ValidationError('Система в превью не подписана для Secure Boot; ключи не записаны')
    unsigned = check_signatures(runner, chroot, record)
    if unsigned:
        raise ValidationError('Не подписаны для Secure Boot: ' + ', '.join(unsigned) + '. Ключи не записаны')
    emit('final-progress', text='Записываю ключи Secure Boot этой системы в прошивку (вместе с ключами Microsoft)')
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
        warning = ('Ключи Secure Boot не записаны — ' + (lines[-1] if lines else type(exc).__name__)[:300]
                   + '. Система подписана и загрузится; чтобы включить Secure Boot, после входа выполните: '
                   'sudo sbctl enroll-keys --microsoft, затем включите Secure Boot в настройках UEFI')
        record['warnings'] = record.get('warnings', []) + [warning]
        emit('final-warning', text=warning)


def finalize(request, runner):
    config, disk = checked_request(request)
    target = config.disk
    firmware = 'uefi' if Path('/sys/firmware/efi').is_dir() else 'bios'
    boot_number = 1 if firmware == 'uefi' else 2
    passphrase = request.pop('passphrase')
    mount = Path(tempfile.mkdtemp(prefix='agi-final-', dir='/mnt'))
    source = Source(runner, request['image'])
    opened_target = False
    dst = None
    try:
        emit('final-progress', text='Opening the preview for checking')
        source.attach()
        src_root, encrypted = source.open_root(boot_number + 1, passphrase)
        record = read_record(runner, src_root, mount)
        check_record(record, config, firmware, encrypted)
        if source.opened:
            runner.run(['cryptsetup', 'close', SOURCE_MAP]); source.opened = False
        if request['image']['on_target']:
            source.detach()
            boot, root_partition, _ = promote(runner, request, disk, source, firmware)
            root = root_partition
            if encrypted:
                runner.run(['cryptsetup', 'open', '--key-file', '-', root_partition, TARGET_MAP], input_text=passphrase)
                opened_target = True
                root = '/dev/mapper/' + TARGET_MAP
            dst = mount / 'target'
            dst.mkdir()
            runner.run(['mount', root, str(dst)])
            runner.run(['mount', boot, str(dst / 'boot')])
            if record.get('hibernation'):
                discard_hibernation_image(runner, dst)
            moved = False
        else:
            # The swap directory (a subvolume on btrfs) is recreated, not copied.
            skip = [str(Path(SWAPFILE).parent)] if record.get('hibernation') else []
            swap_size = swapfile_size(record) if skip else 0
            boot, root_partition, root, encrypted, dst = copy(runner, request, disk, source, firmware, passphrase, mount,
                                                              skip, swap_size)
            opened_target = encrypted
            moved = True
        passphrase = None
        chroot = ['arch-chroot', str(dst)]
        if moved:
            emit('final-progress', text='Updating partition IDs in the new system')
            root_uuid = runner.run(['blkid', '-s', 'UUID', '-o', 'value', root]).strip()
            luks_uuid = runner.run(['blkid', '-s', 'UUID', '-o', 'value', root_partition]).strip() if encrypted else None
            resume = None
            if record.get('hibernation'):
                resume = recreate_swapfile(runner, dst, root_uuid, record, swap_size)
            (dst / 'etc/fstab').write_text(runner.run(['genfstab', '-U', str(dst)]) + (swap_fstab_line() if resume else ''))
            options = boot_options(root_uuid, luks_uuid, resume)
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
        if config.bootloader == 'systemd-boot':
            runner.run([*chroot, 'bootctl', '--esp-path=/boot', 'install'])
        elif firmware == 'uefi':
            runner.run([*chroot, 'grub-install', '--target=x86_64-efi', '--efi-directory=/boot', '--bootloader-id=AGIOS', '--removable'])
            runner.run([*chroot, 'grub-install', '--target=x86_64-efi', '--efi-directory=/boot', '--bootloader-id=AGIOS'])
            runner.run([*chroot, 'grub-mkconfig', '-o', '/boot/grub/grub.cfg'])
        else:
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
                warning = 'Подписи Secure Boot не подтверждены: ' + ', '.join(unsigned)[:300] + '. Выполните sudo sbctl verify'
                record['warnings'] = record.get('warnings', []) + [warning]
                emit('final-warning', text=warning)
        # A new acceptance ID: the preview's first-boot result must not count for real hardware.
        record['finalization'] = {'preview_id': record['id'], 'target': target, 'mode': 'copy' if moved else 'promote',
                                  'layout': request['layout'], 'target_fingerprint': disk['fingerprint'], 'live_firmware': firmware}
        record['id'] = uuid.uuid4().hex
        record['configuration']['disk'] = target
        record['status'] = 'final_first_boot_pending'
        (dst / 'var/lib/agi-os/installation.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
        runner.run(['sync'])
        runner.run(['umount', str(dst / 'boot')])
        runner.run(['umount', str(dst)])
        dst = None
        if opened_target:
            runner.run(['cryptsetup', 'close', TARGET_MAP]); opened_target = False
        emit('finalized', text='The system on ' + target + ' is ready to boot. Shut down Live, remove the stick and power on the computer.',
             target=target, record_id=record['id'], mode='copy' if moved else 'promote')
    finally:
        passphrase = None
        request.pop('passphrase', None)
        if dst and dst.exists():
            subprocess.run(['umount', '-R', str(dst)], capture_output=True)
        if opened_target:
            subprocess.run(['cryptsetup', 'close', TARGET_MAP], capture_output=True)
        source.detach()
        for child in ('source', 'target'):
            try: (mount / child).rmdir()
            except OSError: pass
        try: mount.rmdir()
        except OSError: pass


def main():
    try:
        with open('/run/agi-os-finalize.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            request = adopt(json.loads(sys.stdin.readline(1000000)))
            LOG.info('finalize.start', 'Завершение установки', layout=request.get('layout'), target=request.get('target'))
            finalize(request, Runner(LOG))
            LOG.info('finalize.done', 'Завершение установки выполнено')
    except Exception as exc:
        known = isinstance(exc, ValidationError)
        LOG.error('finalize.failed', str(exc) if known else 'Внутренняя ошибка завершения', exc=None if known else exc)
        emit('final-error', text=str(exc) if known else 'Finishing stopped on an internal error: ' + type(exc).__name__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
