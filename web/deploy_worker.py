#!/usr/bin/env python3
"""Privileged final-disk transfer. Runs only inside Live, never on the dev host."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

from settings import ENGINE
sys.path.insert(0, str(ENGINE))
from domain import Configuration, ValidationError
from system import live_environment
from worker import Runner, emit, partition_path
from deployment import image_identity, review

DATA = Path('/var/lib/agi-os')


def checked_request(request):
    if os.geteuid() != 0 or not live_environment():
        raise ValidationError('Запись конечного диска разрешена только внутри Live')
    if set(request) != {'source', 'identity', 'configuration', 'target', 'digest', 'confirmation'}:
        raise ValidationError('Неизвестный запрос переноса')
    source = Path(request['source'])
    resolved = source.resolve()
    if (source != resolved or resolved.name != 'system.qcow2'
            or resolved.parent.parent != DATA / 'vm' or not resolved.parent.name.startswith('web-')):
        raise ValidationError('Неверный путь образа превью')
    config = Configuration.parse(request['configuration'])
    current = review(source, config, request['target'])
    if request['digest'] != current['digest'] or request['identity'] != current['identity']:
        raise ValidationError('Диск или образ изменился после проверки')
    if request['confirmation'] != request['target']:
        raise ValidationError('Введите точный путь конечного диска для подтверждения')
    return source, config, current


def transfer(request, runner):
    source, config, consent = checked_request(request)
    target = consent['target']
    info = json.loads(runner.run(['qemu-img', 'info', '--output=json', str(source)]))
    if info['format'] != 'qcow2' or info.get('backing-filename') or info.get('encrypted'):
        raise ValidationError('Требуется самостоятельный незашифрованный qcow2')
    size = info['virtual-size']
    if consent['disk']['size'] < size:
        raise ValidationError('Конечный диск меньше образа превью')
    runner.run(['qemu-img', 'check', '-f', 'qcow2', str(source)])
    runner.run(['modprobe', 'nbd', 'max_part=16'])
    nbd = next((Path('/dev') / ('nbd'+str(i)) for i in range(16)
                if Path('/sys/class/block/nbd'+str(i)).exists()
                and not Path('/sys/class/block/nbd'+str(i)+'/pid').exists()), None)
    if nbd is None:
        raise ValidationError('Нет свободного NBD для проверки образа')
    root = Path(tempfile.mkdtemp(prefix='agi-deploy-', dir='/mnt'))
    connected = mounted = boot_mounted = False
    try:
        # qemu-nbd holds QEMU's shared image lock throughout validation/copy.
        runner.run(['qemu-nbd', '--read-only', '--format=qcow2', '--connect', str(nbd), str(source)])
        connected = True
        runner.run(['partprobe', str(nbd)])
        deadline = time.monotonic() + 30
        while not Path(partition_path(str(nbd), 2)).is_block_device():
            if time.monotonic() >= deadline:
                raise ValidationError('Разделы образа не появились после подключения NBD')
            time.sleep(.1)
        runner.run(['udevadm', 'settle', '--timeout=30'])
        src_root = partition_path(str(nbd), 2)
        emit('deploy-progress', text='Проверяю выключенное превью и файловую систему')
        runner.run(['e2fsck', '-f', '-n', src_root])
        runner.run(['mount', '-o', 'ro,noload', src_root, str(root)])
        mounted = True
        record = json.loads((root/'var/lib/agi-os/installation.json').read_text())
        if record['firmware'] != 'uefi' or Configuration.parse(record['configuration']).digest() != config.digest():
            raise ValidationError('Превью не соответствует согласованной конфигурации')
        runner.run(['umount', str(root)])
        mounted = False
        # Recheck actual disk identity and mounted children immediately before writing.
        checked_request(request)
        emit('deploy-progress', text='Переношу проверенную систему на '+target)
        runner.run(['qemu-img', 'convert', '-n', '-f', 'qcow2', '-O', 'raw', str(source), target], timeout=7200)
        runner.run(['sync'])
        emit('deploy-progress', text='Проверяю записанные данные побайтно')
        with nbd.open('rb', buffering=0) as original, open(target, 'rb', buffering=0) as copied:
            remaining = size
            reported = 0
            while remaining:
                count = min(4 * 2**20, remaining)
                a, b = original.read(count), copied.read(count)
                if len(a) != count or a != b:
                    raise ValidationError('Проверка записанного образа не пройдена')
                remaining -= count
                percent = (size - remaining) * 100 // size
                if percent >= reported + 10:
                    reported = percent
                    emit('deploy-progress', text=f'Проверяю записанные данные побайтно: {percent}%')
        if image_identity(source) != request['identity']:
            raise ValidationError('Образ изменился во время переноса')
        runner.run(['qemu-nbd', '--disconnect', str(nbd)])
        connected = False
        emit('deploy-progress', text='Расширяю раздел и настраиваю загрузку конечной системы')
        runner.run(['sgdisk', '-e', target])
        if consent['disk']['size'] > size:
            runner.run(['parted', '--script', target, 'resizepart', '2', '100%'])
        runner.run(['partprobe', target])
        runner.run(['udevadm', 'settle', '--timeout=30'])
        dst_root, esp = partition_path(target, 2), partition_path(target, 1)
        runner.run(['e2fsck', '-f', '-y', dst_root])
        runner.run(['resize2fs', dst_root])
        runner.run(['mount', dst_root, str(root)])
        mounted = True
        runner.run(['mount', esp, str(root/'boot')])
        boot_mounted = True
        runner.run(['arch-chroot', str(root), 'mkinitcpio', '-P'])
        if config.bootloader == 'systemd-boot':
            runner.run(['arch-chroot', str(root), 'bootctl', '--esp-path=/boot', 'install'])
        else:
            runner.run(['arch-chroot', str(root), 'grub-install', '--target=x86_64-efi',
                        '--efi-directory=/boot', '--bootloader-id=AGIOS', '--removable'])
            runner.run(['arch-chroot', str(root), 'grub-mkconfig', '-o', '/boot/grub/grub.cfg'])
        # A new acceptance ID requires checking the final machine, not reusing
        # the successful preview's first-boot/persistence result.
        record['deployment'] = {'preview_id': record['id'], 'target': target,
                                'target_fingerprint': consent['fingerprint'], 'preview_digest': config.digest()}
        record['id'] = uuid.uuid4().hex
        record['configuration']['disk'] = target
        record['status'] = 'final_first_boot_pending'
        (root/'var/lib/agi-os/installation.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
        runner.run(['sync'])
        runner.run(['umount', str(root/'boot')]); boot_mounted = False
        runner.run(['umount', str(root)]); mounted = False
        emit('deployed', text='Система установлена на '+target+'. Выключите Live, извлеките носитель и загрузитесь с этого диска.',
             target=target, record_id=record['id'])
    finally:
        if boot_mounted:
            subprocess.run(['umount', str(root/'boot')], capture_output=True)
        if mounted:
            subprocess.run(['umount', str(root)], capture_output=True)
        if connected:
            subprocess.run(['qemu-nbd', '--disconnect', str(nbd)], capture_output=True)
        if not root.is_mount():
            try: root.rmdir()
            except OSError: pass


def main():
    try:
        with open('/run/agi-os-deploy.lock', 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            transfer(json.loads(sys.stdin.readline(1000000)), Runner())
    except Exception as exc:
        emit('deploy-error', text=str(exc))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
