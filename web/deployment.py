"""Target-disk inventory and consent bindings for installing onto the computer's disk."""
import hashlib
import json
from pathlib import Path
from domain import ValidationError
from hardware import digest as hardware_digest
from system import inventory, selected_disk

TEST_MARKER = Path('/sys/firmware/qemu_fw_cfg/by_name/opt/org.agi-os.test/raw')


def target_inventory():
    """Physical disks of this computer that may receive the system. Never the Live medium."""
    snapshot = inventory()
    if not snapshot['live']:
        raise ValidationError('Установка доступна только в загруженной Live-среде')
    return restrict_test_targets(snapshot)


def restrict_test_targets(snapshot):
    """In the marked test VM only the disk with serial AGIOS_TARGET may be a target.
    The root helpers apply this too, so a test run never touches the host's other disks."""
    if TEST_MARKER.exists():
        for disk in snapshot['disks']:
            if (disk.get('serial') or '').strip() != 'AGIOS_TARGET':
                disk['eligible'] = False
                disk['reason'] = 'В тесте разрешён только отдельный диск AGIOS_TARGET'
    return snapshot


def orphan_previews(snapshot, current=None):
    """Preview partitions left by an earlier Live session (label AGIOS-PREVIEW), never the active one."""
    found = []
    for disk in snapshot['disks']:
        for part in disk.get('partitions', []):
            if part.get('partlabel') == 'AGIOS-PREVIEW' and part['path'] != current and not part.get('mounted'):
                found.append({'disk': disk['path'], 'device': part['path'], 'size': part['size']})
    return found


def consent(config, snapshot):
    """Bind the reviewed configuration to the exact disk identity and boot mode."""
    disk = selected_disk(snapshot, config.disk)
    binding = {'configuration': config.digest(), 'fingerprint': disk['fingerprint'],
               'target': config.disk, 'firmware': snapshot['firmware'],
               'hardware': hardware_digest(snapshot['hardware'], config.packages, config.session)}
    digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    return {**binding, 'digest': digest, 'disk': disk,
            'warning': 'Все разделы и данные выбранного диска будут удалены до запуска превью.'}
