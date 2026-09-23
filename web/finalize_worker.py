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

Afterwards the initramfs is rebuilt for this computer's hardware, the boot
loader is registered with the firmware and a new acceptance ID is recorded.
"""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from settings import ENGINE
sys.path.insert(0, str(ENGINE))
from domain import Configuration, ValidationError
from system import inventory, live_environment, selected_disk
from worker import CRYPT_NAME, Runner, emit, partition_path

SECTOR = 512
GIB = 2**30
ALIGN = 2048
SOURCE_MAP = 'agi-final-source'
TARGET_MAP = 'agi-final-target'
TYPES = {'bios': 'ef02', 'boot': 'ef00', 'linux': '8300'}


def run_json(runner, args):
    return json.loads(runner.run(args))


def checked_request(request):
    if os.geteuid() != 0 or not live_environment():
        raise ValidationError('Finishing the installation is allowed only inside Live')
    if set(request) != {'target', 'fingerprint', 'configuration', 'passphrase', 'image', 'layout', 'confirmation'}:
        raise ValidationError('Unknown finishing request')
    config = Configuration.parse(request['configuration'])
    if config.disk != request['target'] or request['confirmation'] != request['target']:
        raise ValidationError('Type the exact path of the target disk to confirm')
    if request['layout'] not in ('erase', 'alongside'):
        raise ValidationError('Unknown layout')
    disk = selected_disk(inventory(), request['target'])
    if disk['fingerprint'] != request['fingerprint']:
        raise ValidationError('The disk changed after you confirmed; nothing was finished')
    passphrase = request['passphrase']
    if not isinstance(passphrase, str) or any(c in passphrase for c in '\n\r\x00'):
        raise ValidationError('Invalid encryption password')
    image = request['image']
    if image.get('format') not in ('qcow2', 'raw') or not isinstance(image.get('path'), str):
        raise ValidationError('Invalid preview image description')
    return config, disk


class Source:
    """Read-only access to the preview's partitions and root filesystem."""

    def __init__(self, runner, image):
        self.runner, self.image = runner, image
        self.device = None
        self.nbd = None
        self.loop = None
        self.opened = False
        self.mount = None

    def attach(self):
        if self.image['format'] == 'qcow2':
            self.runner.run(['modprobe', 'nbd', 'max_part=16'])
            self.nbd = next((f'/dev/nbd{i}' for i in range(16) if Path(f'/sys/class/block/nbd{i}').exists()
                             and not Path(f'/sys/class/block/nbd{i}/pid').exists()), None)
            if self.nbd is None:
                raise ValidationError('No free NBD device for the preview image')
            self.runner.run(['qemu-nbd', '--read-only', '--format=qcow2', '--connect', self.nbd, self.image['path']])
            self.device = self.nbd
            self.runner.run(['partprobe', self.nbd])
        else:
            self.loop = self.runner.run(['losetup', '--find', '--show', '--read-only', '--partscan', self.image['path']]).strip()
            self.device = self.loop
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
            self.runner.run(['cryptsetup', 'open', '--readonly', '--key-file', '-', device, SOURCE_MAP], input_text=passphrase)
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
            subprocess.run(['qemu-nbd', '--disconnect', self.nbd], capture_output=True)
            self.nbd = None
        if self.loop:
            subprocess.run(['losetup', '--detach', self.loop], capture_output=True)
            self.loop = None


def read_record(runner, root_device, mount):
    runner.run(['mount', '-o', 'ro', root_device, str(mount)])
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
    # Erase the nested table signatures now sitting in gaps between real partitions.
    runner.run(['dd', 'if=/dev/zero', f'of={target}', 'bs=512', f'seek={base}', 'count=34', 'conv=notrunc,fsync'])
    tail = base + int(entry['size']) - 33
    runner.run(['dd', 'if=/dev/zero', f'of={target}', 'bs=512', f'seek={tail}', 'count=33', 'conv=notrunc,fsync'])
    runner.run(['partprobe', target])
    runner.run(['udevadm', 'settle', '--timeout=30'])
    refreshed = run_json(runner, ['sfdisk', '--json', target])['partitiontable']['partitions']
    def node(kind):
        start = kinds[kind][0]
        return next(p['node'] for p in refreshed if int(p['start']) == start)
    return node('boot'), node('linux'), False


def copy(runner, request, disk, source, firmware, passphrase, mount):
    """Create fresh partitions on the target and copy the preview into them file by file."""
    target = disk['path']
    boot_number = 1 if firmware == 'uefi' else 2
    root_number = boot_number + 1
    src_root, encrypted = source.open_root(root_number, passphrase)
    src_mount = mount / 'source'
    src_mount.mkdir()
    runner.run(['mount', '-o', 'ro', src_root, str(src_mount)])
    source.mount = src_mount
    runner.run(['mount', '-o', 'ro', source.partition(boot_number), str(src_mount / 'boot')])
    used = int(runner.run(['du', '-sxB1', str(src_mount)]).split()[0]) + int(runner.run(['du', '-sB1', str(src_mount / 'boot')]).split()[0])
    needed = used + used // 5 + 2 * GIB
    emit('final-progress', text=f'Creating partitions on {target} for {used / GIB:.1f} GiB of data')
    if request['layout'] == 'erase':
        runner.run(['sgdisk', '--zap-all', target])
        runner.run(['sgdisk', '--clear', target])
    else:
        runner.run(['sgdisk', f'--backup=/run/agi-final-{Path(target).name}.gpt', target])
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
    runner.run(['rsync', '-aHAX', '--numeric-ids', '--exclude=/boot/*', f'{src_mount}/', f'{dst}/'], timeout=14400)
    # The boot partition is FAT on UEFI: copy contents without POSIX ownership or modes.
    runner.run(['rsync', '-rt', '--no-perms', '--no-owner', '--no-group', '--modify-window=2', f'{src_mount}/boot/', f'{dst}/boot/'], timeout=3600)
    emit('final-progress', text='Verifying the copy by checksums')
    differences = runner.run(['rsync', '-aHAXcn', '--numeric-ids', '--exclude=/boot/*', '--out-format=%n', f'{src_mount}/', f'{dst}/'], timeout=14400).strip()
    differences += runner.run(['rsync', '-rcn', '--no-perms', '--no-owner', '--no-group', '--out-format=%n', f'{src_mount}/boot/', f'{dst}/boot/'], timeout=3600).strip()
    if differences:
        raise ValidationError('The copy did not pass the check: ' + differences.splitlines()[0])
    runner.run(['umount', str(src_mount / 'boot')])
    runner.run(['umount', str(src_mount)])
    source.mount = None
    return boot, root_partition, root, encrypted, dst


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
        on_target = request['image']['format'] == 'raw' and request['image']['path'].startswith(target)
        if on_target:
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
            moved = False
        else:
            boot, root_partition, root, encrypted, dst = copy(runner, request, disk, source, firmware, passphrase, mount)
            opened_target = encrypted
            moved = True
        passphrase = None
        chroot = ['arch-chroot', str(dst)]
        if moved:
            emit('final-progress', text='Updating partition IDs in the new system')
            (dst / 'etc/fstab').write_text(runner.run(['genfstab', '-U', str(dst)]))
            root_uuid = runner.run(['blkid', '-s', 'UUID', '-o', 'value', root]).strip()
            options = f'root=UUID={root_uuid} rw'
            if encrypted:
                luks_uuid = runner.run(['blkid', '-s', 'UUID', '-o', 'value', root_partition]).strip()
                options = f'cryptdevice=UUID={luks_uuid}:{CRYPT_NAME} root=/dev/mapper/{CRYPT_NAME} rw'
                defaults = dst / 'etc/default/grub'
                if defaults.exists():
                    lines = [l for l in defaults.read_text().splitlines() if not l.startswith('GRUB_CMDLINE_LINUX=')]
                    defaults.write_text('\n'.join(lines) + f'\nGRUB_CMDLINE_LINUX="cryptdevice=UUID={luks_uuid}:{CRYPT_NAME}"\n')
            for entry in (dst / 'boot/loader/entries').glob('*.conf') if (dst / 'boot/loader/entries').is_dir() else []:
                text = '\n'.join(('options ' + options) if line.startswith('options ') else line for line in entry.read_text().splitlines())
                entry.write_text(text + '\n')
            record['root_uuid'] = root_uuid
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
            finalize(json.loads(sys.stdin.readline(1000000)), Runner())
    except Exception as exc:
        emit('final-error', text=str(exc) if isinstance(exc, ValidationError) else 'Finishing stopped on an internal error: ' + type(exc).__name__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
