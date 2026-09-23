#!/usr/bin/env python3
"""Privileged preview-storage operations (probe, prepare, revert). Runs only inside Live.

Every prepared location is reversible except an explicitly chosen disk erase:
- ram:       a zram block device with ext4 holding the preview image; revert frees it.
- file:      one image file in the free space of an existing filesystem; revert deletes it.
- partition: one new partition in unpartitioned space; revert deletes that entry only.
- shrink:    an NTFS/ext4 partition is shrunk and the freed space holds the new
             partition; revert deletes it, restores the boundary and grows the filesystem.
- erase:     the whole target disk becomes one preview partition (not reversible).
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from settings import DATA_ROOT, ENGINE
sys.path.insert(0, str(ENGINE))
from domain import ValidationError
from journal import Logger, adopt
from system import inventory, live_environment, read_command
from worker import Runner, partition_path

PREVIEW = DATA_ROOT / 'preview'
SECTOR = 512
MIB = 2**20
GIB = 2**30
ALIGN = MIB // SECTOR
NAME = 'AGIOS-PREVIEW'
FILE_FS = ('ext4', 'exfat', 'ntfs', 'btrfs', 'xfs', 'f2fs', 'vfat')
SHRINK_FS = ('ntfs', 'ext4')
RESERVE = 3 * GIB  # Live desktop, browser, guacd and the site itself (measured ≈ 2.5 GiB).
COMPRESSION = 1.3  # Conservative zram ratio for a freshly installed system (measured ≈ 1.35).
LOG = Logger('storage')


def sh(args, timeout=120, input_text=None):
    try:
        output = read_command(args, timeout=timeout) if input_text is None else subprocess.run(
            args, input=input_text, text=True, capture_output=True, timeout=timeout, check=True,
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}).stdout
    except Exception as exc:
        LOG.warning('command.failed', f'{args[0]}: {type(exc).__name__}', args=list(args),
                    stderr=getattr(exc, 'stderr', None))
        raise
    LOG.info('command.done', args[0], args=list(args))
    return output


def mem_available():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) * 1024
    raise ValidationError('Не удалось прочитать объём памяти')


def free_regions(disk):
    """Unpartitioned, 1 MiB aligned regions of a disk as (start_sector, end_sector) inclusive."""
    total = disk['size'] // SECTOR
    if not disk.get('pttype'):
        if disk.get('fstype'):
            return []  # A filesystem written directly to the whole device is user data.
        return [(2048, total - 34)]
    try:
        table = json.loads(sh(['sfdisk', '--json', disk['path']]))['partitiontable']
    except (ValidationError, ValueError, KeyError):
        return []
    if table.get('label') != 'gpt':
        return []  # MBR disks: only the explicit whole-disk erase converts them.
    first, last = int(table.get('firstlba', 2048)), int(table.get('lastlba', total - 34))
    used = sorted((int(p['start']), int(p['start']) + int(p['size']) - 1) for p in table.get('partitions', []))
    regions, cursor = [], first
    for start, end in used:
        if start - cursor >= 2 * ALIGN:
            regions.append((cursor, start - 1))
        cursor = max(cursor, end + 1)
    if last - cursor >= 2 * ALIGN:
        regions.append((cursor, last))
    aligned = []
    for start, end in regions:
        start = (start + ALIGN - 1) // ALIGN * ALIGN
        end = (end + 1) // ALIGN * ALIGN - 1
        if end - start + 1 >= 2 * ALIGN:
            aligned.append((start, end))
    return aligned


def mounted_free(device, fstype):
    """Free bytes inside a filesystem, read through a temporary read-only mount."""
    point = PREVIEW / 'probe'
    point.mkdir(parents=True, exist_ok=True)
    kind = ['-t', 'ntfs3'] if fstype == 'ntfs' else []
    result = subprocess.run(['mount', '-o', 'ro', *kind, device, str(point)], capture_output=True, timeout=60)
    if result.returncode:
        return None
    try:
        stat = os.statvfs(point)
        return stat.f_bavail * stat.f_frsize
    finally:
        subprocess.run(['umount', str(point)], capture_output=True, timeout=60)


def fs_free(partition):
    fstype = partition.get('fstype')
    if fstype not in FILE_FS or partition['mounted']:
        return None
    return mounted_free(partition['path'], fstype)


def shrink_room(partition):
    """How far an unmounted NTFS/ext4 filesystem can shrink safely, in bytes (or None)."""
    fstype = partition.get('fstype')
    if fstype not in SHRINK_FS or partition['mounted']:
        return None
    try:
        if fstype == 'ntfs':
            info = sh(['ntfsresize', '--no-action', '--info', '--force', partition['path']], timeout=300)
            for line in info.splitlines():
                if 'might resize at' in line:
                    smallest = int(line.split('at', 1)[1].split()[0])
                    return max(0, partition['size'] - smallest - GIB)
            return None
        sh(['e2fsck', '-f', '-n', partition['path']], timeout=600)
        smallest = int(sh(['resize2fs', '-P', partition['path']], timeout=300).rsplit(':', 1)[1].strip())
        block = next(int(line.split(':', 1)[1]) for line in sh(['tune2fs', '-l', partition['path']]).splitlines()
                     if line.startswith('Block size:'))
        return max(0, partition['size'] - smallest * block - GIB)
    except (ValidationError, ValueError, subprocess.CalledProcessError):
        return None


def probe(request):
    needed, target, vm_memory = int(request['needed']), request['target'], int(request['vm_memory'])
    compression = float(request.get('compression', COMPRESSION))
    snapshot = inventory()
    disks = {d['path']: d for d in snapshot['disks']}
    if target not in disks:
        raise ValidationError('Целевой диск не найден')
    options = []
    budget = mem_available() - vm_memory - RESERVE
    options.append({'id': 'ram', 'kind': 'ram', 'title': 'В оперативной памяти',
                    'detail': f'Сжатый образ (zram). Доступно ≈ {budget / GIB:.1f} ГиБ после выделения VM'
                              + (' — зашифрованные данные не сжимаются' if compression <= 1 else ''),
                    'revert': 'Диски не затрагиваются: выключить VM — и всё',
                    'destructive': False, 'confirm': None, 'available': max(0, budget),
                    'fits': needed / compression <= budget, 'order': 0})
    live_medium = read_command(['findmnt', '-n', '-o', 'SOURCE', '/run/archiso/bootmnt']).strip()
    for disk in snapshot['disks']:
        tran = disk.get('tran') or ('usb' if disk.get('rm') else 'disk')
        if disk['path'] != target:
            for part in disk['partitions']:
                if part['path'] == live_medium:
                    continue
                free = fs_free(part)
                if free is None:
                    continue
                limit = min(free, 4 * GIB - MIB) if part['fstype'] == 'vfat' else free
                options.append({'id': 'file:' + part['path'], 'kind': 'file', 'title': f'Файл на {part["path"]}',
                                'detail': f'{part["fstype"]} «{part.get("label") or disk.get("model") or ""}», свободно {free / GIB:.1f} ГиБ, {tran}'
                                          + (' — FAT32 ограничивает файл 4 ГиБ' if part['fstype'] == 'vfat' else ''),
                                'revert': 'Удалить файл AGIOS-PREVIEW/preview.qcow2; остальное не менялось',
                                'destructive': False, 'confirm': None, 'device': part['path'], 'fstype': part['fstype'],
                                'available': limit, 'fits': needed <= limit, 'order': 1 if tran != 'usb' else 2})
        for start, end in free_regions(disk):
            size = (end - start + 1) * SECTOR
            options.append({'id': f'part:{disk["path"]}:{start}', 'kind': 'partition',
                            'title': f'Новый раздел в свободном месте {disk["path"]}',
                            'detail': f'Неразмечено {size / GIB:.1f} ГиБ, {disk.get("model") or tran}'
                                      + (' — это целевой диск, разделы превью станут разделами системы без копирования' if disk['path'] == target else ''),
                            'revert': 'Удалить одну добавленную запись раздела; существующие разделы не менялись',
                            'destructive': False, 'confirm': None, 'disk': disk['path'], 'start': start, 'end': end,
                            'available': size, 'fits': needed <= size, 'order': 1 if disk['path'] == target else 2})
        if disk['path'] == target and disk.get('pttype') == 'gpt':
            for part in disk['partitions']:
                room = shrink_room(part)
                if room is None or room < needed:
                    continue
                options.append({'id': 'shrink:' + part['path'], 'kind': 'shrink', 'title': f'Ужать раздел {part["path"]}',
                                'detail': f'{part["fstype"]} «{part.get("label") or ""}» {part["size"] / GIB:.1f} ГиБ → освободить {needed / GIB:.1f} ГиБ. '
                                          'Данные сохраняются; рекомендуется резервная копия',
                                'revert': 'Удалить раздел превью, вернуть границу раздела и вырастить файловую систему обратно',
                                'destructive': True, 'confirm': part['path'], 'disk': disk['path'], 'device': part['path'],
                                'fstype': part['fstype'], 'available': room, 'fits': True, 'order': 3})
    disk = disks[target]
    options.append({'id': 'erase:' + target, 'kind': 'erase', 'title': f'Стереть весь диск {target} сейчас',
                    'detail': f'{disk["size"] / GIB:.1f} ГиБ{", " + disk["model"] if disk.get("model") else ""}. Все данные будут удалены до превью',
                    'revert': 'Необратимо', 'destructive': True, 'confirm': target, 'disk': target,
                    'available': disk['size'], 'fits': needed <= disk['size'] - 2 * GIB, 'order': 4})
    fitting = [o for o in options if o['fits']]
    fitting.sort(key=lambda o: (o['destructive'], o['order']))
    if fitting:
        fitting[0]['recommended'] = True
    return {'needed': needed, 'options': options}


def gpt_backup(disk):
    PREVIEW.mkdir(parents=True, exist_ok=True)
    backup = PREVIEW / (Path(disk).name + '.gpt')
    sh(['sgdisk', f'--backup={backup}', disk])
    return str(backup)


def new_partition(disk, start, end):
    partitions = {p['path'] for p in inventory_disk(disk)['partitions']}
    sh(['sgdisk', f'--new=0:{start}:{end}', '--typecode=0:8300', f'--change-name=0:{NAME}', disk])
    sh(['partprobe', disk])
    sh(['udevadm', 'settle', '--timeout=30'])
    created = [p['path'] for p in inventory_disk(disk)['partitions'] if p['path'] not in partitions]
    if len(created) != 1:
        raise ValidationError('Не удалось определить созданный раздел превью')
    return created[0]


def inventory_disk(disk):
    return next(d for d in inventory()['disks'] if d['path'] == disk)


def release_mount(point):
    """Never stack a new preview mount over a stale one left by an interrupted attempt."""
    while os.path.ismount(point):
        if subprocess.run(['umount', str(point)], capture_output=True, timeout=60).returncode:
            raise ValidationError('Каталог превью занят предыдущей операцией: ' + str(point))


def image_file(directory, size):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'preview.qcow2'
    sh(['qemu-img', 'create', '-q', '-f', 'qcow2', str(path), str(size)])
    shutil.chown(directory, 'agi', 'agi')
    shutil.chown(path, 'agi', 'agi')
    return {'format': 'qcow2', 'path': str(path)}


def prepare(request):
    option, needed = request['option'], int(request['needed'])
    virtual = min(max(needed * 2, 16 * GIB), 64 * GIB)  # Sparse capacity of an image-backed preview.
    kind = option['kind']
    PREVIEW.mkdir(parents=True, exist_ok=True)
    PREVIEW.chmod(0o755)  # QEMU runs as agi and must reach the image inside.
    if kind == 'ram':
        budget = mem_available() - int(request['vm_memory']) - RESERVE
        if needed / float(request.get('compression', COMPRESSION)) > budget:
            raise ValidationError('Для превью в памяти недостаточно свободной RAM')
        subprocess.run(['modprobe', 'zram'], capture_output=True, timeout=30)
        device = sh(['zramctl', '--find', '--size', str(virtual), '--algorithm', 'zstd']).strip()
        Path('/sys/block', Path(device).name, 'mem_limit').write_text(str(int(budget)))
        sh(['mkfs.ext4', '-q', '-O', '^has_journal', device])
        point = PREVIEW / 'ram'
        point.mkdir(exist_ok=True)
        release_mount(point)
        sh(['mount', '-o', 'discard,noatime', device, str(point)])
        shutil.chown(point, 'agi', 'agi')
        return {'image': image_file(point, virtual), 'revert': {'kind': 'ram', 'device': device, 'mount': str(point)},
                'monitor': f'/sys/block/{Path(device).name}/mm_stat', 'budget': int(budget)}
    if kind == 'file':
        point = PREVIEW / 'media'
        point.mkdir(exist_ok=True)
        release_mount(point)
        fstype = option['fstype']
        options = 'noatime'
        if fstype in ('ntfs', 'exfat', 'vfat'):
            options += ',uid=agi,gid=agi'
        sh(['mount', '-o', options, *(['-t', 'ntfs3'] if fstype == 'ntfs' else []), option['device'], str(point)])
        folder = point / NAME
        stat = os.statvfs(point)
        if stat.f_bavail * stat.f_frsize < needed:
            subprocess.run(['umount', str(point)], capture_output=True)
            raise ValidationError('На выбранном носителе стало меньше свободного места, чем нужно')
        limit = min(virtual, 4 * GIB - MIB) if fstype == 'vfat' else virtual
        image = image_file(folder, limit)
        return {'image': image, 'revert': {'kind': 'file', 'device': option['device'], 'mount': str(point), 'folder': str(folder)}}
    if kind == 'partition':
        disk = option['disk']
        current = inventory_disk(disk)
        if not current.get('pttype'):
            if current.get('fstype'):
                raise ValidationError('На носителе есть файловая система без таблицы разделов')
            sh(['sgdisk', '--clear', disk])
        backup = gpt_backup(disk)
        regions = dict((s, e) for s, e in free_regions(inventory_disk(disk)))
        start = int(option['start'])
        if start not in regions:
            raise ValidationError('Свободное место на носителе изменилось; обновите варианты')
        end = min(regions[start], start + max(needed * 2, 16 * GIB) // SECTOR - 1) if disk != request['target'] else regions[start]
        end = (end + 1) // ALIGN * ALIGN - 1
        device = new_partition(disk, start, end)
        return {'image': {'format': 'raw', 'path': device},
                'revert': {'kind': 'partition', 'disk': disk, 'device': device, 'backup': backup}}
    if kind == 'shrink':
        disk, device, fstype = option['disk'], option['device'], option['fstype']
        part = next(p for p in inventory_disk(disk)['partitions'] if p['path'] == device)
        if part['mounted']:
            raise ValidationError('Раздел смонтирован')
        new_size = (part['size'] - needed) // MIB * MIB
        if fstype == 'ntfs':
            sh(['ntfsresize', '--no-action', '--force', '--size', str(new_size), device], timeout=1800)
            sh(['ntfsresize', '--force', '--size', str(new_size), device], timeout=7200, input_text='y\n')
        else:
            sh(['e2fsck', '-f', '-y', device], timeout=1800)
            sh(['resize2fs', device, f'{new_size // MIB}M'], timeout=7200)
        backup = gpt_backup(disk)
        number = int(''.join(c for c in device[len(disk):] if c.isdigit()))
        start = int(part['start'])
        new_end = start + new_size // SECTOR - 1
        sh(['parted', '--script', disk, 'resizepart', str(number), f'{new_end}s'])
        sh(['partprobe', disk])
        sh(['udevadm', 'settle', '--timeout=30'])
        regions = free_regions(inventory_disk(disk))
        region = next(((s, e) for s, e in regions if s > new_end and (e - s + 1) * SECTOR >= needed), None)
        if region is None:
            raise ValidationError('После ужатия не появилось ожидаемое свободное место')
        created = new_partition(disk, region[0], region[1])
        return {'image': {'format': 'raw', 'path': created},
                'revert': {'kind': 'shrink', 'disk': disk, 'device': created, 'shrunk': device, 'fstype': fstype,
                           'number': number, 'original_end': start + part['size'] // SECTOR - 1, 'backup': backup}}
    if kind == 'erase':
        disk = option['disk']
        sh(['sgdisk', '--zap-all', disk])
        sh(['sgdisk', '--clear', disk])
        regions = free_regions(inventory_disk(disk))
        device = new_partition(disk, regions[0][0], regions[0][1])
        return {'image': {'format': 'raw', 'path': device}, 'revert': {'kind': 'erase', 'disk': disk, 'device': device}}
    raise ValidationError('Неизвестный вид хранилища превью')


def delete_partition(disk, device):
    number = int(''.join(c for c in device[len(disk):] if c.isdigit()))
    sh(['wipefs', '--all', device])
    sh(['sgdisk', f'--delete={number}', disk])
    sh(['partprobe', disk])
    sh(['udevadm', 'settle', '--timeout=30'])


def revert(request):
    state = request['state']
    kind = state['kind']
    if kind == 'ram':
        subprocess.run(['umount', state['mount']], capture_output=True, timeout=60)
        sh(['zramctl', '--reset', state['device']])
        return {'reverted': True, 'text': 'Память освобождена; диски не менялись'}
    if kind == 'file':
        if Path(state['folder']).is_dir():
            shutil.rmtree(state['folder'])
        sh(['sync'])
        subprocess.run(['umount', state['mount']], capture_output=True, timeout=120)
        return {'reverted': True, 'text': 'Файл превью удалён; носитель в исходном состоянии'}
    if kind == 'partition':
        delete_partition(state['disk'], state['device'])
        return {'reverted': True, 'text': 'Раздел превью удалён; остальные разделы не менялись'}
    if kind == 'shrink':
        delete_partition(state['disk'], state['device'])
        sh(['parted', '--script', state['disk'], 'resizepart', str(state['number']), f'{state["original_end"]}s'])
        sh(['partprobe', state['disk']])
        sh(['udevadm', 'settle', '--timeout=30'])
        if state['fstype'] == 'ntfs':
            sh(['ntfsresize', '--force', state['shrunk']], timeout=7200, input_text='y\n')
        else:
            sh(['e2fsck', '-f', '-y', state['shrunk']], timeout=1800)
            sh(['resize2fs', state['shrunk']], timeout=7200)
        return {'reverted': True, 'text': 'Раздел превью удалён, граница раздела восстановлена, файловая система выращена обратно'}
    if kind == 'erase':
        return {'reverted': False, 'text': 'Диск был стёрт по явному выбору; вернуть данные невозможно'}
    raise ValidationError('Неизвестный вид хранилища превью')


def main():
    try:
        if os.geteuid() != 0 or not live_environment():
            raise ValidationError('Операции с носителями разрешены только внутри Live')
        request = adopt(json.loads(sys.stdin.readline(1_000_000)))
        global PREVIEW
        data_root = Path(request.get('data_root', DATA_ROOT))
        if not data_root.is_absolute():
            raise ValidationError('Некорректный каталог данных')
        PREVIEW = data_root / 'preview'
        handler = {'probe': probe, 'prepare': prepare, 'revert': revert}[request['op']]
        LOG.info('op.start', request['op'], op=request['op'])
        result = handler(request)
        LOG.info('op.done', request['op'], op=request['op'])
        print(json.dumps({'result': result}, ensure_ascii=False))
    except Exception as exc:
        text = str(exc) if isinstance(exc, (ValidationError, KeyError)) else 'Внутренняя ошибка операции с носителем'
        if isinstance(exc, subprocess.CalledProcessError):
            text = 'Команда завершилась ошибкой: ' + ' '.join(exc.cmd[:2])
        known = isinstance(exc, ValidationError)
        LOG.error('op.failed', text, exc=None if known else exc)
        print(json.dumps({'error': text}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
