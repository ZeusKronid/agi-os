"""Target-disk inventory and consent bindings for installing onto the computer's disk."""
import hashlib
import json
from pathlib import Path
from domain import ValidationError
from system import inventory, selected_disk

TEST_MARKER = Path('/sys/firmware/qemu_fw_cfg/by_name/opt/org.agi-os.test/raw')


def target_inventory():
    """Physical disks of this computer that may receive the system. Never the Live medium."""
    snapshot = inventory()
    if not snapshot['live']:
        raise ValidationError('Installing is available only in the booted Live environment')
    test = TEST_MARKER.exists()
    for disk in snapshot['disks']:
        if test and (disk.get('serial') or '').strip() != 'AGIOS_TARGET':
            disk['eligible'] = False
            disk['reason'] = 'In a test only the separate AGIOS_TARGET disk is allowed'
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
               'target': config.disk, 'firmware': snapshot['firmware']}
    digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    return {**binding, 'digest': digest, 'disk': disk,
            'warning': 'All partitions and data on the selected disk are deleted before the preview starts.'}
