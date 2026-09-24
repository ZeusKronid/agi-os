#!/usr/bin/env python3
"""Privileged preview-storage operations (probe, prepare, revert). Runs only inside Live.

Every prepared location is reversible except an explicitly chosen disk erase:
- ram:       a zram block device with ext4 holding the preview image; revert frees it.
- file:      one image file in the free space of an existing filesystem; revert deletes it.
- partition: one new partition in unpartitioned space; revert deletes that entry only.
- shrink:    an NTFS/ext4 partition is shrunk and the freed space holds the new
             partition; revert deletes it, restores the boundary and grows the filesystem.
- erase:     the whole target disk becomes one preview partition (not reversible).

Every non-memory preview also carries a secret-free preview record (see
preview_record.py) so that a restarted Live can find it again: scan lists the
previews on this computer's media, adopt reattaches one, remove undoes one found
after a restart and mark updates the record of the active preview.

The caller (the website, user agi-web) is not trusted: every request is checked
against a strict schema and a fresh inventory, devices are re-derived from the
option id instead of taken from the request, and only partitions this helper
labelled AGIOS-PREVIEW are ever deleted. See docs/root-helpers-threat-model.md.
"""
import json
import math
import os
from pathlib import Path
import re
import stat as stat_module
import subprocess
import sys

from settings import ENGINE
sys.path.insert(0, str(ENGINE))
from domain import ValidationError
# The journal helper that takes the caller's trace id is imported under another name:
# adopt() below is the operation that reattaches a found preview.
from journal import Logger, adopt as adopt_trace
from system import inventory, live_environment, read_command, selected_disk
from worker import Runner, partition_path
from deployment import restrict_test_targets
from preview_record import (FILE_LIMIT, GAP_BYTES, GAP_END, GAP_START, clean, decode_file, decode_gap,
                            encode_file, encode_gap)

# Mount points and GPT backups live in a root-owned runtime directory, never in the
# site's writable data directory: the site must not be able to swap them for symlinks.
PREVIEW = Path('/run/agi-os-preview')
SECTOR = 512
MIB = 2**20
GIB = 2**30
ALIGN = MIB // SECTOR
NAME = 'AGIOS-PREVIEW'
FILE_FS = ('ext4', 'exfat', 'ntfs', 'btrfs', 'xfs', 'f2fs', 'vfat')
SHRINK_FS = ('ntfs', 'ext4')
TIB = 2**40
RESERVE = 3 * GIB  # Live desktop, browser, guacd and the site itself (measured ≈ 2.5 GiB).
COMPRESSION = 1.3  # Conservative zram ratio for a freshly installed system (measured ≈ 1.35).
BLANK_PROBE = MIB  # A disk without any signature must also be zero here before it counts as empty.
LOG = Logger('storage')
RECORD = 'preview.json'
FOREIGN = 'nosuid,nodev,noexec'  # Media are foreign data: never honour setuid files or device nodes on them.
# Read-only mounts that also skip journal replay: looking must not write to the medium.
READ_ONLY = {'ext4': 'ro,noload', 'xfs': 'ro,norecovery', 'f2fs': 'ro,norecovery', 'btrfs': 'ro,rescue=nologreplay'}


def sh(args, timeout=120, input_text=None):
    try:
        output = read_command(args, timeout=timeout) if input_text is None else subprocess.run(
            args, input=input_text, text=True, capture_output=True, timeout=timeout, check=True,
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'}).stdout
    except Exception as exc:
        # Output of a command fed on stdin is not logged: the input may be a secret.
        LOG.warning('command.failed', f'{args[0]}: {type(exc).__name__}', args=list(args),
                    stderr=getattr(exc, 'stderr', None) if input_text is None else None)
        raise
    LOG.info('command.done', args[0], args=list(args))
    return output


NO_TABLE = 'does not contain a recognized partition table'


def partition_table(device):
    """sfdisk's view of a device's partition table, or None when there is none. A blank
    disk or a fresh preview partition has no table: that is an answer, not a failure,
    and must not look like one in the journal."""
    args = ['sfdisk', '--json', device]
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=120,
                                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    except Exception as exc:
        LOG.warning('command.failed', f'sfdisk: {type(exc).__name__}', args=args)
        raise ValidationError('sfdisk could not read the partition table') from exc
    if result.returncode and NO_TABLE in result.stderr:
        LOG.debug('table.none', 'No partition table', device=device)
        return None
    if result.returncode:
        LOG.warning('command.failed', f'sfdisk: code {result.returncode}', args=args, stderr=result.stderr)
        raise ValidationError('sfdisk could not read the partition table')
    LOG.info('command.done', 'sfdisk', args=args)
    try:
        return json.loads(result.stdout)['partitiontable']
    except (ValueError, KeyError, TypeError) as exc:
        raise ValidationError('sfdisk returned an unexpected answer') from exc


def mem_available():
    for line in Path('/proc/meminfo').read_text().splitlines():
        if line.startswith('MemAvailable:'):
            return int(line.split()[1]) * 1024
    raise ValidationError('Could not read the memory size')


def free_regions(disk):
    """Unpartitioned, 1 MiB aligned regions of a disk as (start_sector, end_sector) inclusive."""
    total = disk['size'] // SECTOR
    if not disk.get('pttype'):
        if disk.get('fstype') or not looks_blank(disk['path']):
            return []  # A filesystem or signature-less data (e.g. a VeraCrypt disk) is user data.
        return [(2048, total - 34)]
    try:
        table = partition_table(disk['path'])
    except ValidationError:
        return []
    if table is None or table.get('label') != 'gpt':
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


def looks_blank(path):
    """True only when the start of a device holds nothing but zeros."""
    try:
        with open(path, 'rb') as device:
            head = device.read(BLANK_PROBE)
    except OSError:
        return False
    return bool(head) and not head.strip(b'\0')


def read_only_mount(device, fstype, point):
    point = private_dir(point)
    release_mount(point)
    kind = ['-t', 'ntfs3'] if fstype == 'ntfs' else []
    # A foreign medium must not bring setuid programs or device nodes with it.
    result = subprocess.run(['mount', '-o', READ_ONLY.get(fstype, 'ro') + ',' + FOREIGN, *kind, device, str(point)],
                            capture_output=True, timeout=60)
    return result.returncode == 0


def mounted_free(device, fstype):
    """Free bytes inside a filesystem, read through a temporary read-only mount."""
    point = PREVIEW / 'probe'
    if not read_only_mount(device, fstype, point):
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


# ---- Input validation: the request comes from an unprivileged process ----

REQUEST_KEYS = {
    # sparse: bytes of a reserved but unwritten hibernation swap file (CMP-120), 0..needed.
    'probe': ({'op', 'needed', 'target', 'vm_memory'}, {'compression', 'sparse'}),
    'prepare': ({'op', 'option', 'needed', 'target', 'vm_memory'}, {'compression', 'sparse'}),
    'revert': ({'op', 'state'}, set()),
    'scan': ({'op'}, set()),
    'adopt': ({'op', 'id'}, set()),
    'remove': ({'op', 'id'}, set()),
    'mark': ({'op', 'record', 'revert'}, set()),
}
STATE_KEYS = {
    'ram': {'kind', 'device', 'mount'},
    'file': {'kind', 'device', 'mount', 'folder'},
    'partition': {'kind', 'disk', 'device', 'backup'},
    'shrink': {'kind', 'disk', 'device', 'shrunk', 'fstype', 'number', 'start', 'original_end', 'backup'},
    'erase': {'kind', 'disk', 'device'},
}
DEVICE = re.compile(r'/dev/[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}')


def whole(value, name, low, high):
    """An integer from JSON (bool is not a number here) within [low, high]."""
    if type(value) is not int or not low <= value <= high:
        raise ValidationError(f'Invalid value: {name}')
    return value


def text(value, name, pattern=DEVICE):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValidationError(f'Invalid value: {name}')
    return value


def checked_request(request):
    if not isinstance(request, dict) or not isinstance(request.get('op'), str) or request['op'] not in REQUEST_KEYS:
        raise ValidationError('Unknown storage operation')
    required, optional = REQUEST_KEYS[request['op']]
    keys = set(request) - {'data_root'}  # Sent by older sites; ignored, the helper never uses the caller's paths.
    if not required <= keys <= required | optional:
        raise ValidationError('Invalid storage operation request')
    return {k: v for k, v in request.items() if k in keys}


def sizing(request):
    needed = whole(request['needed'], 'needed', 1, 64 * TIB)
    target = text(request['target'], 'target')
    vm_memory = whole(request['vm_memory'], 'vm_memory', 0, 4 * TIB)
    compression = request.get('compression', COMPRESSION)
    if type(compression) not in (int, float) or not math.isfinite(compression) or not 1 <= compression <= 4:
        raise ValidationError('Invalid value: compression')
    if 'sparse' in request:
        whole(request['sparse'], 'sparse', 0, needed)
    return needed, target, vm_memory, float(compression)


def private_dir(path):
    """A root-owned directory (0755) that nobody else can replace or write into.
    Parents below PREVIEW get the same treatment: mkdir(parents=True) would create them
    with the caller's umask (0700 was seen in Live), and QEMU must reach the image."""
    if path != PREVIEW and PREVIEW in path.parents:
        private_dir(path.parent)
    path.mkdir(mode=0o755, parents=True, exist_ok=True)
    info = os.lstat(path)
    if stat_module.S_ISDIR(info.st_mode) and os.path.ismount(path):
        # A medium mounted on our own mount point: its root belongs to the medium. Safe because the
        # mount point's directory entry lives in root-owned PREVIEW and cannot be swapped by the site.
        return path
    if not stat_module.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValidationError(f'Unsafe working directory {path}')
    if info.st_mode & 0o777 != 0o755:
        os.chmod(path, 0o755)
    return path


def live_source():
    try:
        return read_command(['findmnt', '-n', '-o', 'SOURCE', '/run/archiso/bootmnt']).strip()
    except ValidationError:
        return ''


def live_medium_disk(snapshot):
    """The disk Live booted from (a USB stick is a 'disk' too); never a preview location."""
    source = live_source()
    for disk in snapshot['disks']:
        if source and (disk['path'] == source or any(p['path'] == source for p in disk['partitions'])):
            return disk['path']
    return None


def mount_source(point):
    result = subprocess.run(['findmnt', '-n', '-o', 'SOURCE', '--mountpoint', str(point)],
                            capture_output=True, text=True, timeout=30)
    return result.stdout.strip() if result.returncode == 0 else None


def partition_number(disk, device):
    suffix = device[len(disk):] if device.startswith(disk) else ''
    match = re.fullmatch(r'p?([1-9][0-9]{0,2})', suffix)
    if not match or (suffix.startswith('p') != disk[-1].isdigit()):
        raise ValidationError(f'{device} is not a partition of {disk}')
    return int(match.group(1))


def find_partition(snapshot, device):
    """(disk, partition) of a partition path in the current inventory."""
    for disk in snapshot['disks']:
        for part in disk['partitions']:
            if part['path'] == device:
                partition_number(disk['path'], device)
                return disk, part
    raise ValidationError(f'Partition {device} not found')


def usable_disk(snapshot, path):
    """A writable disk that is not the Live medium."""
    disk = next((d for d in snapshot['disks'] if d['path'] == path), None)
    if disk is None:
        raise ValidationError(f'Disk {path} not found')
    if disk.get('ro') or path == live_medium_disk(snapshot):
        raise ValidationError(f'Disk {path} can’t be used for the preview')
    return disk


def resolve_option(option, target, snapshot):
    """Rebuild the chosen option from its id and the current inventory.

    Only the id is taken from the request: the device, disk and filesystem the
    helper touches come from lsblk, so a forged option cannot point elsewhere."""
    if not isinstance(option, dict) or not isinstance(option.get('id'), str):
        raise ValidationError('Invalid preview storage option')
    kind, _, rest = option['id'].partition(':')
    if option.get('kind') not in (None, {'part': 'partition'}.get(kind, kind)):
        raise ValidationError('The preview storage option does not match its ID')
    if kind == 'ram' and not rest:
        return {'kind': 'ram'}
    if kind == 'file':
        disk, part = find_partition(snapshot, text(rest, 'device'))
        usable_disk(snapshot, disk['path'])
        if disk['path'] == target or part['path'] == live_source():
            raise ValidationError('A preview file can only live on another medium')
        if part.get('fstype') not in FILE_FS or part['mounted']:
            raise ValidationError(f'A preview file can’t be placed on {part["path"]}')
        return {'kind': 'file', 'device': part['path'], 'fstype': part['fstype']}
    if kind == 'part':
        disk_path, _, start = rest.rpartition(':')
        disk = usable_disk(snapshot, text(disk_path, 'disk'))
        if not start.isdigit():
            raise ValidationError('Invalid start of the preview partition')
        if disk['path'] == target:
            selected_disk(snapshot, target)
        return {'kind': 'partition', 'disk': disk['path'], 'start': int(start)}
    if kind == 'shrink':
        disk, part = find_partition(snapshot, text(rest, 'device'))
        if disk['path'] != target:
            raise ValidationError('Only a partition of the target disk can be shrunk')
        selected_disk(snapshot, target)
        if disk.get('pttype') != 'gpt' or part.get('fstype') not in SHRINK_FS or part['mounted']:
            raise ValidationError(f'Partition {part["path"]} can’t be shrunk')
        return {'kind': 'shrink', 'disk': disk['path'], 'device': part['path'], 'fstype': part['fstype']}
    if kind == 'erase':
        if rest != target:
            raise ValidationError('Only the chosen target disk can be erased')
        selected_disk(snapshot, target)
        usable_disk(snapshot, target)
        return {'kind': 'erase', 'disk': target}
    raise ValidationError('Unknown preview storage kind')


def preview_partition(snapshot, disk_path, device):
    """A partition of that disk created by this helper (GPT name AGIOS-PREVIEW), not in use."""
    disk, part = find_partition(snapshot, text(device, 'device'))
    if disk['path'] != disk_path:
        raise ValidationError(f'{device} is not a partition of {disk_path}')
    if part.get('partlabel') != NAME or part['mounted']:
        raise ValidationError(f'{device} is not an unused {NAME} preview partition; it is not deleted')
    usable_disk(snapshot, disk_path)
    return disk, part


def checked_state(state, snapshot):
    """Check a revert record kept by the site (and therefore writable by the site's user)."""
    if not isinstance(state, dict) or not isinstance(state.get('kind'), str) or state['kind'] not in STATE_KEYS:
        raise ValidationError('Unknown preview storage kind')
    kind = state['kind']
    required = STATE_KEYS[kind] - {'backup', 'folder', 'start'}
    if not required <= set(state) <= STATE_KEYS[kind]:
        raise ValidationError('Invalid preview storage record')
    if kind == 'ram':
        text(state['device'], 'device', re.compile(r'/dev/zram[0-9]{1,3}'))
        if state['mount'] != str(PREVIEW / 'ram'):
            raise ValidationError('Invalid preview mount point')
        return state
    if kind == 'file':
        if state['mount'] != str(PREVIEW / 'media') or state.get('folder', str(PREVIEW / 'media' / NAME)) != str(PREVIEW / 'media' / NAME):
            raise ValidationError('Invalid preview mount point')
        disk, part = find_partition(snapshot, text(state['device'], 'device'))
        usable_disk(snapshot, disk['path'])
        if part.get('fstype') not in FILE_FS or (part['mounted'] and mount_source(PREVIEW / 'media') != part['path']):
            raise ValidationError(f'{part["path"]} has no preview file that can be deleted')
        return {**state, 'fstype': part['fstype']}
    if kind == 'erase':
        return state
    disk_path = text(state['disk'], 'disk')
    disk, part = preview_partition(snapshot, disk_path, state['device'])
    if kind == 'partition':
        return state
    # shrink: the shrunk partition directly precedes the preview partition, which gives its space back.
    shrunk_disk, shrunk = find_partition(snapshot, text(state['shrunk'], 'shrunk'))
    number = whole(state['number'], 'number', 1, 999)
    original_end = whole(state['original_end'], 'original_end', 1, 2**48)
    if shrunk_disk['path'] != disk_path or partition_number(disk_path, shrunk['path']) != number or shrunk['mounted']:
        raise ValidationError('Invalid record of the shrunk partition')
    if shrunk.get('fstype') not in SHRINK_FS or state['fstype'] != shrunk['fstype']:
        raise ValidationError('The filesystem of the shrunk partition changed')
    if 'start' in state and state['start'] != int(shrunk['start']):
        raise ValidationError('The start of the shrunk partition changed')
    # Growing back to original_end must only reclaim the preview partition's space.
    shrunk_start, preview_start = int(shrunk['start']), int(part['start'])
    between = [p for p in disk['partitions'] if p['path'] not in (part['path'], shrunk['path'])
               and shrunk_start <= int(p['start'] or 0) <= original_end]
    if not shrunk_start < preview_start <= original_end <= disk['size'] // SECTOR - 34 or between:
        raise ValidationError('The boundary of the shrunk partition does not match the preview partition; nothing is undone')
    return state


def in_memory(request):
    """Bytes an in-memory preview really stores: a reserved but never written area (the
    hibernation swap file) takes room on the image's filesystem, not in zram."""
    needed, sparse = int(request['needed']), int(request.get('sparse', 0))
    if not 0 <= sparse <= needed:
        raise ValidationError('Invalid size of the reserved space')
    return needed - sparse


def probe(request):
    needed, target, vm_memory, compression = sizing(request)
    snapshot = restrict_test_targets(inventory())
    disks = {d['path']: d for d in snapshot['disks']}
    if target not in disks:
        raise ValidationError('Target disk not found')
    selected_disk(snapshot, target)
    live_disk = live_medium_disk(snapshot)
    options = []
    budget = mem_available() - vm_memory - RESERVE
    options.append({'id': 'ram', 'kind': 'ram', 'title': 'In memory',
                    'detail': f'A compressed image (zram). About {budget / GIB:.1f} GiB free after the VM takes its share'
                              + (' — encrypted data does not compress' if compression <= 1 else '')
                              + (f'; the hibernation swap file ({int(request["sparse"]) / GIB:.0f} GiB) is only reserved: it takes memory '
                                 'only if the preview starts swapping to it (then the overall memory limit applies)'
                                 if int(request.get('sparse', 0)) else ''),
                    'revert': 'no disk is touched: stop the VM and it’s gone',
                    'destructive': False, 'confirm': None, 'available': max(0, budget),
                    'fits': in_memory(request) / compression <= budget, 'order': 0})
    live_medium = live_source()
    for disk in snapshot['disks']:
        if disk['path'] == live_disk or disk.get('ro'):
            continue
        tran = disk.get('tran') or ('usb' if disk.get('rm') else 'disk')
        if disk['path'] != target:
            for part in disk['partitions']:
                if part['path'] == live_medium:
                    continue
                free = fs_free(part)
                if free is None:
                    continue
                limit = min(free, 4 * GIB - MIB) if part['fstype'] == 'vfat' else free
                options.append({'id': 'file:' + part['path'], 'kind': 'file', 'title': f'File on {part["path"]}',
                                'detail': f'{part["fstype"]} “{part.get("label") or disk.get("model") or ""}”, {free / GIB:.1f} GiB free, {tran}'
                                          + (' — FAT32 limits a file to 4 GiB' if part['fstype'] == 'vfat' else ''),
                                'revert': 'delete AGIOS-PREVIEW/preview.qcow2; nothing else changed',
                                'destructive': False, 'confirm': None, 'device': part['path'], 'fstype': part['fstype'],
                                'available': limit, 'fits': needed <= limit, 'order': 1 if tran != 'usb' else 2})
        for start, end in free_regions(disk):
            size = (end - start + 1) * SECTOR
            options.append({'id': f'part:{disk["path"]}:{start}', 'kind': 'partition',
                            'title': f'A new partition in free space on {disk["path"]}',
                            'detail': f'{size / GIB:.1f} GiB unpartitioned, {disk.get("model") or tran}'
                                      + (' — this is the target disk: the preview partitions become the system without copying' if disk['path'] == target else ''),
                            'revert': 'delete one added partition entry; existing partitions stay',
                            'destructive': False, 'confirm': None, 'disk': disk['path'], 'start': start, 'end': end,
                            'available': size, 'fits': needed <= size, 'order': 1 if disk['path'] == target else 2})
        if disk['path'] == target and disk.get('pttype') == 'gpt':
            for part in disk['partitions']:
                room = shrink_room(part)
                if room is None or room < needed:
                    continue
                options.append({'id': 'shrink:' + part['path'], 'kind': 'shrink', 'title': f'Shrink partition {part["path"]}',
                                'detail': f'{part["fstype"]} “{part.get("label") or ""}” {part["size"] / GIB:.1f} GiB → frees {needed / GIB:.1f} GiB. '
                                          'Data stays; a backup is recommended',
                                'revert': 'delete the preview partition, restore the boundary and grow the filesystem back',
                                'destructive': True, 'confirm': part['path'], 'disk': disk['path'], 'device': part['path'],
                                'fstype': part['fstype'], 'available': room, 'fits': True, 'order': 3})
    disk = disks[target]
    options.append({'id': 'erase:' + target, 'kind': 'erase', 'title': f'Erase the whole disk {target} now',
                    'detail': f'{disk["size"] / GIB:.1f} GiB{", " + disk["model"] if disk.get("model") else ""}. All data is deleted before the preview',
                    'revert': 'not reversible', 'destructive': True, 'confirm': target, 'disk': target,
                    'available': disk['size'], 'fits': needed <= disk['size'] - 2 * GIB, 'order': 4})
    fitting = [o for o in options if o['fits']]
    fitting.sort(key=lambda o: (o['destructive'], o['order']))
    if fitting:
        fitting[0]['recommended'] = True
    return {'needed': needed, 'options': options}


def gpt_backup(disk):
    backup = private_dir(PREVIEW) / (Path(disk).name + '.gpt')
    sh(['sgdisk', f'--backup={backup}', disk])
    return str(backup)


def new_partition(disk, start, end):
    partitions = {p['path'] for p in inventory_disk(disk)['partitions']}
    sh(['sgdisk', f'--new=0:{start}:{end}', '--typecode=0:8300', f'--change-name=0:{NAME}', disk])
    sh(['partprobe', disk])
    sh(['udevadm', 'settle', '--timeout=30'])
    created = [p['path'] for p in inventory_disk(disk)['partitions'] if p['path'] not in partitions]
    if len(created) != 1:
        raise ValidationError('Could not find the created preview partition')
    # Old data under a new entry must not look like a nested table or a preview record.
    sh(['dd', 'if=/dev/zero', f'of={created[0]}', 'bs=1M', 'count=1', 'conv=fsync'], timeout=60)
    # Nor like half of one: a GPT keeps its backup in the last sectors, and a backup left by an
    # earlier preview of the same size makes the installer's sgdisk --zap-all fail (code 2).
    sectors = int(sh(['blockdev', '--getsz', created[0]]).strip())
    tail = min(sectors, MIB // 512)
    sh(['dd', 'if=/dev/zero', f'of={created[0]}', 'bs=512', f'seek={sectors - tail}', f'count={tail}', 'conv=fsync'],
       timeout=60)
    return created[0]


def inventory_disk(disk):
    return next(d for d in inventory()['disks'] if d['path'] == disk)


def site_owner():
    """The unprivileged website that called this helper through sudo (it runs QEMU)."""
    return int(os.environ.get('SUDO_UID', 0)), int(os.environ.get('SUDO_GID', 0))


def release_mount(point):
    """Never stack a new preview mount over a stale one left by an interrupted attempt."""
    while os.path.ismount(point):
        if subprocess.run(['umount', str(point)], capture_output=True, timeout=60).returncode:
            raise ValidationError('A previous operation still holds the preview directory: ' + str(point))


def image_file(directory, size):
    """Create the preview image for QEMU (the site's user) without following planted symlinks."""
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise ValidationError(f'{directory} is not a regular directory; no preview is created here')
    directory.mkdir(exist_ok=True)
    path = directory / 'preview.qcow2'
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValidationError(f'{path} is not a regular file; no preview is created here')
    sh(['qemu-img', 'create', '-q', '-f', 'qcow2', str(path), str(size)])
    for item in (directory, path):
        os.chown(item, *site_owner(), follow_symlinks=False)
    return {'format': 'qcow2', 'path': str(path)}


def prepare(request):
    needed, target, vm_memory, compression = sizing(request)
    option = resolve_option(request['option'], target, restrict_test_targets(inventory()))
    # Sparse capacity of an image-backed preview; never below what the system needs.
    virtual = max(min(max(needed * 2, 16 * GIB), 64 * GIB), needed)
    kind = option['kind']
    private_dir(PREVIEW)  # 0755: QEMU runs as the website's user and must reach the image inside.
    if kind == 'ram':
        budget = mem_available() - vm_memory - RESERVE
        if in_memory(request) / compression > budget:
            raise ValidationError('Not enough free RAM for an in-memory preview')
        subprocess.run(['modprobe', 'zram'], capture_output=True, timeout=30)
        device = sh(['zramctl', '--find', '--size', str(virtual), '--algorithm', 'zstd']).strip()
        Path('/sys/block', Path(device).name, 'mem_limit').write_text(str(int(budget)))
        sh(['mkfs.ext4', '-q', '-O', '^has_journal', device])
        point = private_dir(PREVIEW / 'ram')
        release_mount(point)
        sh(['mount', '-o', 'discard,noatime,' + FOREIGN, device, str(point)])
        os.chown(point, *site_owner(), follow_symlinks=False)
        return {'image': image_file(point, virtual), 'revert': {'kind': 'ram', 'device': device, 'mount': str(point)},
                'monitor': f'/sys/block/{Path(device).name}/mm_stat', 'budget': int(budget)}
    if kind == 'file':
        point = private_dir(PREVIEW / 'media')
        release_mount(point)
        fstype = option['fstype']
        options = 'noatime,' + FOREIGN
        if fstype in ('ntfs', 'exfat', 'vfat'):
            options += ',uid=%d,gid=%d' % site_owner()
        sh(['mount', '-o', options, *(['-t', 'ntfs3'] if fstype == 'ntfs' else []), option['device'], str(point)])
        folder = point / NAME
        stat = os.statvfs(point)
        if stat.f_bavail * stat.f_frsize < needed:
            subprocess.run(['umount', str(point)], capture_output=True)
            raise ValidationError('The selected medium now has less free space than needed')
        limit = min(virtual, 4 * GIB - MIB) if fstype == 'vfat' else virtual
        image = image_file(folder, limit)
        return {'image': image, 'revert': {'kind': 'file', 'device': option['device'], 'mount': str(point), 'folder': str(folder)}}
    if kind == 'partition':
        disk = option['disk']
        current = inventory_disk(disk)
        if not current.get('pttype'):
            if current.get('fstype') or not looks_blank(disk):
                raise ValidationError('The medium has data but no partition table; it is not partitioned')
            sh(['sgdisk', '--clear', disk])
        backup = gpt_backup(disk)
        regions = dict((s, e) for s, e in free_regions(inventory_disk(disk)))
        start = int(option['start'])
        if start not in regions:
            raise ValidationError('Free space on the medium changed; refresh the options')
        end = min(regions[start], start + max(needed * 2, 16 * GIB) // SECTOR - 1) if disk != target else regions[start]
        end = (end + 1) // ALIGN * ALIGN - 1
        device = new_partition(disk, start, end)
        return {'image': {'format': 'raw', 'path': device},
                'revert': {'kind': 'partition', 'disk': disk, 'device': device, 'backup': backup}}
    if kind == 'shrink':
        disk, device, fstype = option['disk'], option['device'], option['fstype']
        part = next(p for p in inventory_disk(disk)['partitions'] if p['path'] == device)
        if part['mounted']:
            raise ValidationError('The partition is mounted')
        new_size = (part['size'] - needed) // MIB * MIB
        if new_size < GIB:
            raise ValidationError('The partition is too small to free the space needed')
        if fstype == 'ntfs':
            sh(['ntfsresize', '--no-action', '--force', '--size', str(new_size), device], timeout=1800)
            sh(['ntfsresize', '--force', '--size', str(new_size), device], timeout=7200, input_text='y\n')
        else:
            sh(['e2fsck', '-f', '-y', device], timeout=1800)
            sh(['resize2fs', device, f'{new_size // MIB}M'], timeout=7200)
        backup = gpt_backup(disk)
        number = partition_number(disk, device)
        start = int(part['start'])
        new_end = start + new_size // SECTOR - 1
        sh(['parted', '--script', disk, 'resizepart', str(number), f'{new_end}s'])
        sh(['partprobe', disk])
        sh(['udevadm', 'settle', '--timeout=30'])
        regions = free_regions(inventory_disk(disk))
        region = next(((s, e) for s, e in regions if s > new_end and (e - s + 1) * SECTOR >= needed), None)
        if region is None:
            raise ValidationError('Shrinking did not leave the expected free space')
        created = new_partition(disk, region[0], region[1])
        return {'image': {'format': 'raw', 'path': created},
                'revert': {'kind': 'shrink', 'disk': disk, 'device': created, 'shrunk': device, 'fstype': fstype,
                           'number': number, 'start': start, 'original_end': start + part['size'] // SECTOR - 1,
                           'backup': backup}}
    if kind == 'erase':
        disk = option['disk']
        sh(['sgdisk', '--zap-all', disk])
        sh(['sgdisk', '--clear', disk])
        regions = free_regions(inventory_disk(disk))
        device = new_partition(disk, regions[0][0], regions[0][1])
        return {'image': {'format': 'raw', 'path': device}, 'revert': {'kind': 'erase', 'disk': disk, 'device': device}}
    raise ValidationError('Unknown preview storage kind')


def delete_partition(disk, device):
    number = partition_number(disk, device)
    clear_gap(device)
    sh(['wipefs', '--all', device])
    sh(['sgdisk', f'--delete={number}', disk])
    sh(['partprobe', disk])
    sh(['udevadm', 'settle', '--timeout=30'])


def revert(request):
    state = checked_state(request['state'], inventory())
    kind = state['kind']
    if kind == 'ram':
        subprocess.run(['umount', state['mount']], capture_output=True, timeout=60)
        sh(['zramctl', '--reset', state['device']])
        return {'reverted': True, 'text': 'Memory freed; no disk was changed'}
    if kind == 'file':
        point = Path(state['mount'])
        if mount_source(point) != state['device']:
            # After a Live restart the medium is no longer mounted: mount it again to remove the file.
            release_mount(private_dir(point))
            options = 'noatime,' + FOREIGN
            sh(['mount', '-o', options, *(['-t', 'ntfs3'] if state['fstype'] == 'ntfs' else []), state['device'], str(point)])
        # Only what AGIOS created goes: the image and its record, then the folder if nothing else is in it.
        folder = point / NAME
        if folder.is_symlink():
            folder.unlink()
        elif folder.is_dir():
            for name in ('preview.qcow2', RECORD, RECORD + '.tmp'):
                if (folder / name).is_symlink() or (folder / name).is_file():
                    (folder / name).unlink()
            try:
                folder.rmdir()
            except OSError:
                pass  # The user put something else there; it stays.
        sh(['sync'])
        subprocess.run(['umount', str(point)], capture_output=True, timeout=120)
        return {'reverted': True, 'text': 'Preview file deleted; the medium is as it was'}
    if kind == 'partition':
        delete_partition(state['disk'], state['device'])
        return {'reverted': True, 'text': 'Preview partition deleted; other partitions stay'}
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
        return {'reverted': True, 'text': 'Preview partition deleted, the boundary restored and the filesystem grown back'}
    if kind == 'erase':
        return {'reverted': False, 'text': 'The disk was erased by your explicit choice; the data can’t come back'}
    raise ValidationError('Unknown preview storage kind')


def read_gap(device):
    with open(device, 'rb') as handle:
        handle.seek(GAP_START * SECTOR)
        return handle.read(GAP_BYTES)


def write_gap(device, frame):
    # O_EXCL refuses a partition that is mounted or held by the kernel (dm, md).
    descriptor = os.open(device, os.O_WRONLY | os.O_EXCL)
    try:
        os.lseek(descriptor, GAP_START * SECTOR, os.SEEK_SET)
        data = frame.ljust(GAP_BYTES, b'\0')
        while data:
            data = data[os.write(descriptor, data):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def clear_gap(device):
    try:
        with open(device, 'rb') as handle:
            handle.seek(GAP_START * SECTOR)
            if not handle.read(len(b'AGIOS')) == b'AGIOS':
                return
        write_gap(device, b'')
    except OSError:
        pass  # The partition is deleted next; an unreadable leftover is never listed again.


def gap_free(device):
    """Nothing of the nested disk (table, entries, partitions) lives in the record area."""
    try:
        table = partition_table(device)
    except ValidationError:
        table = None
    if table is None:
        return True  # No nested table yet: the installation has not partitioned the preview.
    if int(table.get('firstlba', 34)) > GAP_START:
        return False
    return all(int(p['start']) >= GAP_END for p in table.get('partitions', []))


def record_problem(raw):
    if raw is None:
        return None, 'No preview record: installing into it never started, or an older AGIOS version created it'
    try:
        return clean(raw), None
    except ValidationError as exc:
        return None, 'The preview record was rejected: ' + str(exc)


def partition_entry(disk, part):
    entry = {'id': 'partition:' + part['path'], 'kind': 'partition', 'disk': disk['path'],
             'device': part['path'], 'size': part['size'], 'medium': disk.get('model') or disk['path']}
    try:
        entry['record'], entry['problem'] = record_problem(decode_gap(read_gap(part['path'])))
    except OSError:
        entry['record'], entry['problem'] = None, 'The preview partition can’t be read'
    return entry


def safe_folder(point):
    """AGIOS-PREVIEW on a medium: a real directory, never a link out of the medium."""
    folder = point / NAME
    if folder.is_symlink() or not folder.is_dir() or not folder.resolve().is_relative_to(point.resolve()):
        return None
    return folder


def file_entry(disk, part):
    point = PREVIEW / 'scan'
    if not read_only_mount(part['path'], part['fstype'], point):
        return None
    try:
        folder = safe_folder(point)
        image = folder / 'preview.qcow2' if folder else None
        if image is None or image.is_symlink() or not image.is_file():
            return None
        entry = {'id': 'file:' + part['path'], 'kind': 'file', 'disk': disk['path'], 'device': part['path'],
                 'fstype': part['fstype'], 'size': image.stat().st_blocks * 512,
                 'medium': part.get('label') or disk.get('model') or disk['path']}
        meta = folder / RECORD
        raw = None
        if meta.is_file() and not meta.is_symlink() and meta.stat().st_size <= FILE_LIMIT:
            raw = decode_file(meta.read_bytes())
        entry['record'], entry['problem'] = record_problem(raw)
        return entry
    finally:
        subprocess.run(['umount', str(point)], capture_output=True, timeout=60)


def scan(request):
    """Previews left on this computer's media: AGIOS-PREVIEW partitions and preview files."""
    found = []
    live_medium = live_source()
    for disk in inventory()['disks']:
        for part in disk['partitions']:
            if part['path'] == live_medium or part['mounted']:
                continue
            if part.get('partlabel') == NAME:
                found.append(partition_entry(disk, part))
            elif part.get('fstype') in FILE_FS:
                entry = file_entry(disk, part)
                if entry:
                    found.append(entry)
    return {'found': found}


def locate(found_id):
    if not isinstance(found_id, str):
        raise ValidationError('Invalid ID of a found preview')
    kind, _, device = found_id.partition(':')
    for disk in inventory()['disks']:
        for part in disk['partitions']:
            if part['path'] != device or part['mounted']:
                continue
            if kind == 'partition' and part.get('partlabel') == NAME:
                return disk, part, partition_entry(disk, part)
            if kind == 'file' and part.get('fstype') in FILE_FS:
                entry = file_entry(disk, part)
                if entry:
                    return disk, part, entry
    raise ValidationError('The found preview is no longer available; refresh the list')


def shrink_state(disk, part, storage):
    """Undo of a shrink, checked against the current layout: the shrunk partition must
    directly precede the preview and the recorded boundary must lie between them."""
    parts = sorted(disk['partitions'], key=lambda p: int(p['start'] or 0))
    index = next(i for i, p in enumerate(parts) if p['path'] == part['path'])
    before = parts[index - 1] if index else None
    preview_end = int(part['start']) + part['size'] // SECTOR - 1
    if (before is None or int(before['start']) != storage['shrunk_start'] or before['mounted']
            or before.get('fstype') not in SHRINK_FS or before.get('fstype') != storage['fstype']):
        return None
    before_end = int(before['start']) + before['size'] // SECTOR - 1
    if not before_end < storage['original_end'] <= preview_end:
        return None
    number = partition_number(disk['path'], before['path'])
    return {'kind': 'shrink', 'disk': disk['path'], 'device': part['path'], 'shrunk': before['path'],
            'fstype': before['fstype'], 'number': number, 'start': storage['shrunk_start'],
            'original_end': storage['original_end']}


def undo_state(disk, part, entry, remove=False):
    """How to undo a found preview, derived from the current layout (never trusted from the record)."""
    if entry['kind'] == 'file':
        point = PREVIEW / 'media'
        return {'kind': 'file', 'device': part['path'], 'mount': str(point), 'folder': str(point / NAME)}
    storage = (entry.get('record') or {}).get('storage', {})
    if storage.get('kind') == 'shrink':
        state = shrink_state(disk, part, storage)
        if state:
            return state
    if storage.get('kind') == 'erase' and not remove:
        return {'kind': 'erase', 'disk': disk['path'], 'device': part['path']}
    # A plain partition, an erased disk being cleaned up, or a shrink whose boundary no longer matches.
    return {'kind': 'partition', 'disk': disk['path'], 'device': part['path']}


def check_image(image):
    """A preview file from a medium is untrusted: no backing chain, no external data file."""
    info = json.loads(sh(['qemu-img', 'info', '--output=json', '-f', 'qcow2', str(image)], timeout=60))
    specific = (info.get('format-specific') or {}).get('data') or {}
    if info.get('format') != 'qcow2' or info.get('backing-filename') or info.get('full-backing-filename') \
            or specific.get('data-file'):
        raise ValidationError('The preview file refers to other data; it can’t be continued')


def mount_medium(part):
    private_dir(PREVIEW)  # 0755: QEMU runs as the website's user and must reach the image inside.
    point = private_dir(PREVIEW / 'media')
    release_mount(point)
    options = 'noatime,' + FOREIGN + (',uid=%d,gid=%d' % site_owner() if part['fstype'] in ('ntfs', 'exfat', 'vfat') else '')
    sh(['mount', '-o', options, *(['-t', 'ntfs3'] if part['fstype'] == 'ntfs' else []), part['path'], str(point)])
    folder = safe_folder(point)
    if folder is None:
        subprocess.run(['umount', str(point)], capture_output=True, timeout=60)
        raise ValidationError('The medium has no preview folder')
    return point, folder


def adopt(request):
    """Reattach a found, completely installed preview after a Live restart."""
    disk, part, entry = locate(request['id'])
    if entry['record'] is None:
        raise ValidationError(entry['problem'])
    if entry['kind'] == 'file':
        point, folder = mount_medium(part)
        image = folder / 'preview.qcow2'
        try:
            if image.is_symlink() or not image.is_file():
                raise ValidationError('Preview file not found')
            check_image(image)
        except Exception:
            subprocess.run(['umount', str(point)], capture_output=True, timeout=60)
            raise
        for path in (folder, image):  # Never follow a link swapped in after the checks.
            os.chown(path, *site_owner(), follow_symlinks=False)
        described = {'format': 'qcow2', 'path': str(image)}
    else:
        described = {'format': 'raw', 'path': part['path']}
    return {'image': described, 'revert': undo_state(disk, part, entry), 'record': entry['record'],
            'medium': entry['medium']}


def remove(request):
    """Undo a preview found after a restart; other partitions and files stay untouched."""
    disk, part, entry = locate(request['id'])
    state = undo_state(disk, part, entry, remove=True)
    if entry['kind'] == 'file':
        mount_medium(part)
    return revert({'state': state})


def mark(request):
    """Write the record of the active preview into its storage."""
    record = clean(request['record'])
    state = request['revert']
    kind = state.get('kind') if isinstance(state, dict) else None
    if kind == 'ram':
        return {'marked': False}
    if kind == 'file':
        point = PREVIEW / 'media'
        folder = safe_folder(point) if os.path.ismount(point) else None
        if folder is None:
            raise ValidationError('The preview medium is not mounted')
        temp = folder / (RECORD + '.tmp')
        temp.unlink(missing_ok=True)
        with open(temp, 'xb') as handle:
            handle.write(encode_file(record))
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(folder / RECORD)
        return {'marked': True}
    if kind in ('partition', 'shrink', 'erase'):
        snapshot = inventory()
        disk, _ = find_partition(snapshot, text(state.get('device'), 'device'))
        _, part = preview_partition(snapshot, disk['path'], state['device'])
        if not gap_free(part['path']):
            raise ValidationError('The record area of the preview partition is in use')
        write_gap(part['path'], encode_gap(record))
        return {'marked': True}
    raise ValidationError('Unknown preview storage kind')


def main():
    try:
        if os.geteuid() != 0 or not live_environment():
            raise ValidationError('Storage operations are allowed only inside Live')
        request = checked_request(adopt_trace(json.loads(sys.stdin.readline(1_000_000))))
        handler = {'probe': probe, 'prepare': prepare, 'revert': revert, 'scan': scan, 'adopt': adopt,
                   'remove': remove, 'mark': mark}[request['op']]
        LOG.info('op.start', request['op'], op=request['op'])
        result = handler(request)
        LOG.info('op.done', request['op'], op=request['op'])
        print(json.dumps({'result': result}, ensure_ascii=False))
    except Exception as exc:
        text = str(exc) if isinstance(exc, ValidationError) else 'Internal storage operation error'
        if isinstance(exc, subprocess.CalledProcessError):
            text = 'Command failed: ' + ' '.join(exc.cmd[:2])
        known = isinstance(exc, ValidationError)
        LOG.error('op.failed', text, exc=None if known else exc)
        print(json.dumps({'error': text}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
