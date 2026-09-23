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
import subprocess
import sys
import tempfile
import uuid

from settings import ENGINE
sys.path.insert(0, str(ENGINE))
from domain import Configuration, ValidationError
from hardware import driver_plan, initramfs_config, profile
from journal import Logger, adopt
from system import inventory, live_environment, selected_disk
from worker import CRYPT_NAME, Cancelled, Runner, emit, partition_path
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
LOG = Logger('finalize')


def run_json(runner, args):
    return json.loads(runner.run(args))


def checked_request(request):
    if os.geteuid() != 0 or not live_environment():
        raise ValidationError('Завершение установки разрешено только внутри Live')
    if not isinstance(request, dict) or set(request) != {'target', 'fingerprint', 'configuration', 'passphrase', 'image', 'layout', 'confirmation'}:
        raise ValidationError('Неизвестный запрос завершения')
    if not isinstance(request['configuration'], dict) or not all(isinstance(request[k], str) for k in ('target', 'fingerprint', 'confirmation')):
        raise ValidationError('Некорректный запрос завершения')
    config = Configuration.parse(request['configuration'])
    if config.disk != request['target'] or request['confirmation'] != request['target']:
        raise ValidationError('Введите точный путь конечного диска для подтверждения')
    if request['layout'] not in ('erase', 'alongside'):
        raise ValidationError('Неизвестный вариант разметки')
    snapshot = restrict_test_targets(inventory())
    disk = selected_disk(snapshot, request['target'])
    if disk['fingerprint'] != request['fingerprint']:
        raise ValidationError('Диск изменился после подтверждения; завершение отменено')
    passphrase = request['passphrase']
    if not isinstance(passphrase, str) or len(passphrase) > 1024 or any(c in passphrase for c in '\n\r\x00'):
        raise ValidationError('Некорректный пароль шифрования')
    request['image'] = checked_image(request['image'], snapshot, disk)
    return config, disk


def checked_image(image, snapshot, target):
    """The preview must be storage the storage helper prepared, never an arbitrary file or device:
    a qcow2 image inside its root-owned mount points, or a partition named AGIOS-PREVIEW."""
    if not isinstance(image, dict) or set(image) != {'format', 'path'} or not isinstance(image['path'], str):
        raise ValidationError('Некорректное описание образа превью')
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
    raise ValidationError('Некорректное описание образа превью')


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
                raise ValidationError('Нет свободного NBD для образа превью')
            self.runner.run(['qemu-nbd', '--read-only', '--format=qcow2', '--connect', self.nbd, self.image['path']])
            self.device = self.nbd
            self.runner.run(['partprobe', self.nbd])
        else:
            self.loop = self.runner.run(['losetup', '--find', '--show', '--read-only', '--partscan', self.image['path']]).strip()
            self.device = self.loop
        self.runner.run(['udevadm', 'settle', '--timeout=30'])
        table = run_json(self.runner, ['sfdisk', '--json', self.device])['partitiontable']
        if table.get('label') != 'gpt' or not table.get('partitions'):
            raise ValidationError('В превью нет ожидаемой таблицы разделов')
        self.partitions = table['partitions']
        return self

    def partition(self, number):
        return partition_path(self.device, number)

    def open_root(self, root_number, passphrase):
        device = self.partition(root_number)
        kind = self.runner.run(['blkid', '-s', 'TYPE', '-o', 'value', device]).strip()
        if kind == 'crypto_LUKS':
            if not passphrase:
                raise ValidationError('Корень зашифрован: введите пароль шифрования для завершения')
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
    runner.run(['mount', '-o', SOURCE_MOUNT, root_device, str(mount)])
    try:
        return json.loads((mount / 'var/lib/agi-os/installation.json').read_text())
    finally:
        runner.run(['umount', str(mount)])


def check_record(record, config, firmware, encrypted):
    installed = Configuration.parse({**record['configuration'], 'disk': config.disk})
    if installed.digest() != config.digest():
        raise ValidationError('В превью установлена не та конфигурация, которая была подтверждена')
    if record['firmware'] != firmware:
        raise ValidationError('Превью установлено для другого типа загрузки, чем у этого компьютера')
    if bool(record.get('encrypted')) != encrypted:
        raise ValidationError('Состояние шифрования не совпадает с записью установки')


def free_regions(runner, disk_path, size):
    table = run_json(runner, ['sfdisk', '--json', disk_path])['partitiontable']
    if table.get('label') != 'gpt':
        raise ValidationError('Установка рядом с существующими системами возможна только на диске с GPT')
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
        raise ValidationError('Раздел превью не найден на конечном диске')
    base, number = int(entry['start']), int(preview[len(target):].lstrip('p'))
    nested = sorted(source.partitions, key=lambda p: int(p['start']))
    for part in nested:
        if int(part['start']) % ALIGN:
            raise ValidationError('Разделы превью не выровнены; повышение невозможно')
    emit('final-progress', text='Повышаю разделы превью до разделов диска (данные не перемещаются)')
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
    runner.run(['mount', '-o', SOURCE_MOUNT, src_root, str(src_mount)])
    source.mount = src_mount
    runner.run(['mount', '-o', SOURCE_MOUNT, source.partition(boot_number), str(src_mount / 'boot')])
    used = int(runner.run(['du', '-sxB1', str(src_mount)]).split()[0]) + int(runner.run(['du', '-sB1', str(src_mount / 'boot')]).split()[0])
    needed = used + used // 5 + 2 * GIB
    emit('final-progress', text=f'Создаю разделы на {target} для {used / GIB:.1f} ГиБ данных')
    if request['layout'] == 'erase':
        runner.run(['sgdisk', '--zap-all', target])
        runner.run(['sgdisk', '--clear', target])
    else:
        runner.run(['sgdisk', f'--backup=/run/agi-final-{Path(target).name}.gpt', target])
    regions = [r for r in free_regions(runner, target, disk['size']) if (r[1] - r[0] + 1) * SECTOR >= needed]
    if not regions:
        raise ValidationError(f'На диске нет свободного места для системы ({needed / GIB:.1f} ГиБ)')
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
        emit('final-progress', text='Шифрую корневой раздел конечного диска (LUKS2)')
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
    emit('final-progress', text='Копирую проверенную систему пофайлово')
    runner.run(['rsync', '-aHAX', '--numeric-ids', '--exclude=/boot/*', f'{src_mount}/', f'{dst}/'], timeout=14400)
    # The boot partition is FAT on UEFI: copy contents without POSIX ownership or modes.
    runner.run(['rsync', '-rt', '--no-perms', '--no-owner', '--no-group', '--modify-window=2', f'{src_mount}/boot/', f'{dst}/boot/'], timeout=3600)
    emit('final-progress', text='Проверяю копию по контрольным суммам')
    differences = runner.run(['rsync', '-aHAXcn', '--numeric-ids', '--exclude=/boot/*', '--out-format=%n', f'{src_mount}/', f'{dst}/'], timeout=14400).strip()
    differences += runner.run(['rsync', '-rcn', '--no-perms', '--no-owner', '--no-group', '--out-format=%n', f'{src_mount}/boot/', f'{dst}/boot/'], timeout=3600).strip()
    if differences:
        raise ValidationError('Проверка копии не пройдена: ' + differences.splitlines()[0])
    runner.run(['umount', str(src_mount / 'boot')])
    runner.run(['umount', str(src_mount)])
    source.mount = None
    return boot, root_partition, root, encrypted, dst


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
        if initramfs := initramfs_config(plan, encrypted):
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
        emit('final-progress', text='Открываю превью для проверки')
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
            moved = False
        else:
            boot, root_partition, root, encrypted, dst = copy(runner, request, disk, source, firmware, passphrase, mount)
            opened_target = encrypted
            moved = True
        passphrase = None
        chroot = ['arch-chroot', str(dst)]
        if moved:
            emit('final-progress', text='Обновляю идентификаторы разделов в новой системе')
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
        fit_drivers(runner, chroot, dst, config, record, encrypted)
        emit('final-progress', text='Пересобираю initramfs под оборудование этого компьютера')
        runner.run([*chroot, 'mkinitcpio', '-P'])
        emit('final-progress', text='Регистрирую загрузку установленной системы')
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
        emit('finalized', text='Система на ' + target + ' готова к загрузке. Выключите Live, извлеките носитель и включите компьютер.',
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
        emit('final-error', text=str(exc) if known else 'Завершение прервано внутренней ошибкой: ' + type(exc).__name__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
