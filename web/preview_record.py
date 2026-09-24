"""The preview record: what a Live restart needs to find and continue a preview.

The Live data directory lives in RAM, so the site's own session is lost when the
computer restarts. The record is therefore kept in the preview storage itself,
outside every filesystem of the previewed system and outside its encryption:

- file preview:      ``AGIOS-PREVIEW/preview.json`` next to ``preview.qcow2``;
- partition preview: the unused gap of the preview's nested GPT (sectors
  ``GAP_START``..2047 of the preview partition; the nested partitions start at
  sector 2048 and the nested table itself ends at sector 33).

It carries no secrets: the agreed configuration, the consent identity of the
target disk, the storage kind, the installation status and a short journal of
the operations. A record read from a medium is untrusted input; ``clean``
validates it completely and anything destructive (the undo of the storage) is
derived from the current disk layout, never from the record.
"""
import hashlib
import json
import time
import zlib

from domain import Configuration, ValidationError
from hardware import profile

VERSION = 1
SECTOR = 512
GAP_START = 64            # Well after the nested GPT header and entries (sectors 1..33).
GAP_END = 2048            # First sector of the first nested partition.
GAP_BYTES = (GAP_END - GAP_START) * SECTOR
MAGIC = b'AGIOS-PREVIEW-RECORD/1\n'
FILE_LIMIT = 4 * 2**20
STATUSES = ('installing', 'ready', 'failed', 'finalizing')
KINDS = ('file', 'partition', 'shrink', 'erase')
JOURNAL = 60


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


def text(value, limit=500):
    if not isinstance(value, str) or '\x00' in value:
        return ''
    return value[:limit]


def integer(value, low=0, high=2**63):
    if type(value) is not int or not low <= value <= high:
        raise ValidationError('Некорректное число в записи превью')
    return value


def clean(record):
    """A complete, bounded copy of a record, or ValidationError."""
    if not isinstance(record, dict) or record.get('version') != VERSION:
        raise ValidationError('Запись превью неизвестной версии')
    if record.get('status') not in STATUSES:
        raise ValidationError('Неизвестное состояние в записи превью')
    config = Configuration.parse(record.get('configuration'))
    target = record.get('target')
    if not isinstance(target, dict):
        raise ValidationError('В записи превью нет целевого диска')
    storage = record.get('storage')
    if not isinstance(storage, dict) or storage.get('kind') not in KINDS:
        raise ValidationError('Неизвестный вид хранилища в записи превью')
    vm = record.get('vm') if isinstance(record.get('vm'), dict) else {}
    try:
        hardware = profile(record.get('hardware'))
    except ValueError as exc:
        raise ValidationError(str(exc))
    cleaned_storage = {'kind': storage['kind'], 'title': text(storage.get('title'), 200),
                       'revert': text(storage.get('revert'), 300)}
    if storage['kind'] == 'shrink':
        cleaned_storage.update(shrunk_start=integer(storage.get('shrunk_start'), 1),
                               original_end=integer(storage.get('original_end'), 1),
                               fstype=text(storage.get('fstype'), 10))
    record_id = record.get('id')
    if not isinstance(record_id, str) or not record_id.isalnum() or len(record_id) > 64:
        raise ValidationError('Некорректный идентификатор записи превью')
    journal = record.get('journal') if isinstance(record.get('journal'), list) else []
    return {
        'version': VERSION, 'id': record_id, 'status': record['status'],
        'created': text(record.get('created'), 40), 'updated': text(record.get('updated'), 40),
        'error': text(record.get('error'), 1500) or None,
        'configuration': config.as_dict(),
        'encrypted': record.get('encrypted') is True,
        # Signed for Secure Boot in the preview (CMP-121); absent in older records.
        'secure_boot': record.get('secure_boot') is True,
        'firmware': 'bios' if record.get('firmware') == 'bios' else 'uefi',
        'target': {k: text(target.get(k), 200) if k != 'size' else integer(target.get('size'))
                   for k in ('path', 'size', 'model', 'serial', 'wwn')},
        'hardware': hardware,
        'vm': {'memory': vm['memory'] if type(vm.get('memory')) is int and 2048 <= vm['memory'] <= 32768 else 4096,
               'cpus': vm['cpus'] if type(vm.get('cpus')) is int and 1 <= vm['cpus'] <= 16 else 4},
        'storage': cleaned_storage,
        'journal': [{'time': text(e.get('time'), 40), 'text': text(e.get('text'))}
                    for e in journal[-JOURNAL:] if isinstance(e, dict)],
    }


def disk_identity(disk):
    return {'path': disk['path'], 'size': disk['size'], 'model': disk.get('model') or '',
            'serial': disk.get('serial') or '', 'wwn': disk.get('wwn') or ''}


def same_disk(identity, disk):
    """The record's target, possibly under another device name after a restart."""
    current = disk_identity(disk)
    return all(identity.get(k) == current[k] for k in ('size', 'model', 'serial', 'wwn'))


def encode_gap(record):
    body = zlib.compress(json.dumps(record, ensure_ascii=False, sort_keys=True).encode(), 9)
    frame = MAGIC + b'%d\n' % len(body) + body + hashlib.sha256(body).hexdigest().encode() + b'\n'
    if len(frame) > GAP_BYTES:
        raise ValidationError('Запись превью не помещается в служебную область раздела')
    return frame


def decode_gap(data):
    """The record inside a gap area, or None when there is none (or it is damaged)."""
    if not data.startswith(MAGIC):
        return None
    rest = data[len(MAGIC):]
    head, _, rest = rest.partition(b'\n')
    if not head.isdigit() or int(head) > GAP_BYTES:
        return None
    length = int(head)
    body, checksum = rest[:length], rest[length:length + 65]
    if checksum != hashlib.sha256(body).hexdigest().encode() + b'\n':
        return None
    try:
        inflate = zlib.decompressobj()
        plain = inflate.decompress(body, FILE_LIMIT)  # Bounded: a crafted medium cannot inflate without limit.
        if inflate.unconsumed_tail or not inflate.eof:
            return None
        return json.loads(plain.decode())
    except (zlib.error, ValueError, UnicodeDecodeError):
        return None


def encode_file(record):
    data = json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True).encode()
    if len(data) > FILE_LIMIT:
        raise ValidationError('Запись превью слишком большая')
    return data


def decode_file(data):
    if len(data) > FILE_LIMIT:
        return None
    try:
        return json.loads(data.decode())
    except (ValueError, UnicodeDecodeError):
        return None
