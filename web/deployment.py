"""Review bindings for transferring a stopped, tested preview to a real disk."""
import hashlib
import json
from pathlib import Path
from domain import ValidationError
from system import inventory, selected_disk


def image_identity(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValidationError('Образ превью отсутствует или является ссылкой')
    st = path.stat()
    return {'size': st.st_size, 'mtime_ns': st.st_mtime_ns, 'inode': st.st_ino}


def target_inventory():
    snapshot = inventory()
    if not snapshot['live']:
        raise ValidationError('Установка доступна только в загруженной Live-среде')
    test = Path('/sys/firmware/qemu_fw_cfg/by_name/opt/org.agi-os.test/raw').exists()
    for disk in snapshot['disks']:
        if test and (disk.get('serial') or '').strip() != 'AGIOS_TARGET':
            disk['eligible'] = False
            disk['reason'] = 'В тесте разрешён только отдельный диск AGIOS_TARGET'
        if disk['size'] < 32 * 2**30:
            disk['eligible'] = False
            disk['reason'] = 'Для этого превью нужен диск не меньше 32 ГиБ'
    return snapshot


def review(image, config, target):
    snapshot = target_inventory()
    if snapshot['firmware'] != 'uefi' or config.filesystem != 'ext4':
        raise ValidationError('Перенос превью пока поддерживает UEFI и ext4')
    disk = selected_disk(snapshot, target)
    identity = image_identity(image)
    binding = {'source': str(image), 'identity': identity, 'configuration': config.as_dict(),
               'fingerprint': disk['fingerprint'], 'target': target}
    digest = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    return {**binding, 'digest': digest, 'disk': disk,
            'warning': 'Все разделы и данные выбранного диска будут удалены. Пароль и файлы из превью сохранятся.'}
