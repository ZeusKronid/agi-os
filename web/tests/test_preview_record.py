import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zlib
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: F401 (sets the engine import path)
import preview_record
import storage_worker
from controller import DemoProvider
from domain import ValidationError
from hardware import demo

GIB = 2**30


def sample_record(**changes):
    record = {'version': 1, 'id': 'a1b2c3', 'status': 'ready', 'created': '2026-09-23T12:00:00+0300',
              'updated': '2026-09-23T12:30:00+0300', 'error': None,
              'configuration': DemoProvider().reply('', [])['configuration'], 'encrypted': True, 'firmware': 'uefi',
              'target': {'path': '/dev/vda', 'size': 64 * GIB, 'model': 'Disk', 'serial': 'AGIOS_TARGET', 'wwn': ''},
              'hardware': demo(), 'vm': {'memory': 4096, 'cpus': 4},
              'storage': {'kind': 'partition', 'title': 'Новый раздел', 'revert': 'Удалить запись раздела'},
              'journal': [{'time': 't', 'text': 'Хранилище превью подготовлено'}]}
    record.update(changes)
    return record


class RecordFormatTests(unittest.TestCase):
    def test_gap_round_trip_and_damage_detection(self):
        record = preview_record.clean(sample_record())
        frame = preview_record.encode_gap(record)
        self.assertLessEqual(len(frame), preview_record.GAP_BYTES)
        area = frame.ljust(preview_record.GAP_BYTES, b'\0')
        self.assertEqual(preview_record.decode_gap(area), record)
        damaged = bytearray(area)
        damaged[len(preview_record.MAGIC) + 20] ^= 0xFF
        self.assertIsNone(preview_record.decode_gap(bytes(damaged)))
        self.assertIsNone(preview_record.decode_gap(b'\0' * 4096))

    def test_inflation_is_bounded(self):
        body = zlib.compress(b' ' * (preview_record.FILE_LIMIT * 4), 9)
        import hashlib
        frame = preview_record.MAGIC + b'%d\n' % len(body) + body + hashlib.sha256(body).hexdigest().encode() + b'\n'
        self.assertIsNone(preview_record.decode_gap(frame))

    def test_clean_keeps_only_known_fields(self):
        raw = sample_record(password='secret-value', passphrase='secret-value')
        raw['storage']['revert_state'] = {'kind': 'shrink', 'number': 1}
        cleaned = preview_record.clean(raw)
        self.assertNotIn('secret-value', json.dumps(cleaned))
        self.assertNotIn('revert_state', cleaned['storage'])

    def test_clean_rejects_bad_records(self):
        for change in ({'version': 2}, {'status': 'done'}, {'id': '../x'}, {'storage': {'kind': 'ram'}},
                       {'target': None}):
            with self.assertRaises(ValidationError, msg=change):
                preview_record.clean(sample_record(**change))
        config = dict(sample_record()['configuration'], disk='/dev/../etc')
        with self.assertRaises(ValidationError):
            preview_record.clean(sample_record(configuration=config))

    def test_shrink_needs_its_boundary(self):
        storage = {'kind': 'shrink', 'title': 't', 'revert': 'r'}
        with self.assertRaises(ValidationError):
            preview_record.clean(sample_record(storage=storage))
        storage.update(shrunk_start=2048, original_end=4000000, fstype='ntfs')
        self.assertEqual(preview_record.clean(sample_record(storage=storage))['storage']['original_end'], 4000000)

    def test_same_disk_ignores_device_name(self):
        identity = {'path': '/dev/sda', 'size': 1, 'model': 'M', 'serial': 'S', 'wwn': ''}
        self.assertTrue(preview_record.same_disk(identity, {'path': '/dev/sdb', 'size': 1, 'model': 'M', 'serial': 'S', 'wwn': None}))
        self.assertFalse(preview_record.same_disk(identity, {'path': '/dev/sda', 'size': 1, 'model': 'M', 'serial': 'T'}))


class GapStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.device = Path(self.directory.name) / 'partition.img'
        with open(self.device, 'wb') as handle:
            handle.truncate(4 * 2**20)

    def test_write_read_and_clear(self):
        record = preview_record.clean(sample_record())
        storage_worker.write_gap(str(self.device), preview_record.encode_gap(record))
        self.assertEqual(preview_record.decode_gap(storage_worker.read_gap(str(self.device))), record)
        data = self.device.read_bytes()
        self.assertEqual(data[:preview_record.GAP_START * 512], b'\0' * preview_record.GAP_START * 512)
        self.assertEqual(data[preview_record.GAP_END * 512:], b'\0' * (len(data) - preview_record.GAP_END * 512))
        storage_worker.clear_gap(str(self.device))
        self.assertIsNone(preview_record.decode_gap(storage_worker.read_gap(str(self.device))))

    def test_gap_must_be_unused_by_the_nested_disk(self):
        table = {'partitiontable': {'label': 'gpt', 'firstlba': 34, 'partitions': [{'start': 2048, 'size': 100}]}}
        with patch.object(storage_worker, 'partition_table', return_value=table['partitiontable']):
            self.assertTrue(storage_worker.gap_free('/dev/x'))
        table['partitiontable']['partitions'][0]['start'] = 40
        with patch.object(storage_worker, 'partition_table', return_value=table['partitiontable']):
            self.assertFalse(storage_worker.gap_free('/dev/x'))
        with patch.object(storage_worker, 'partition_table', return_value=None):
            self.assertTrue(storage_worker.gap_free('/dev/x'))
        with patch.object(storage_worker, 'partition_table', side_effect=ValidationError('unreadable')):
            self.assertTrue(storage_worker.gap_free('/dev/x'))

    def test_partition_entry_reports_missing_record(self):
        disk = {'path': '/dev/vda', 'model': 'Disk'}
        part = {'path': str(self.device), 'size': 4 * 2**20}
        entry = storage_worker.partition_entry(disk, part)
        self.assertIsNone(entry['record'])
        self.assertIn('Записи превью нет', entry['problem'])
        storage_worker.write_gap(str(self.device), preview_record.encode_gap(preview_record.clean(sample_record())))
        entry = storage_worker.partition_entry(disk, part)
        self.assertEqual(entry['record']['status'], 'ready')
        self.assertIsNone(entry['problem'])

    def test_mark_partition_only_for_labelled_unmounted_preview(self):
        record = sample_record()
        snapshot = {'disks': [{'path': '/dev/vda', 'size': 64 * GIB, 'ro': False, 'partitions': [
            {'path': '/dev/vda1', 'partlabel': 'AGIOS-PREVIEW', 'mounted': False, 'size': 1, 'start': 2048},
            {'path': '/dev/vda2', 'partlabel': 'DATA', 'mounted': False, 'size': 1, 'start': 9000}]}]}
        write_gap = storage_worker.write_gap
        written = []
        def write_device(device, frame):  # /dev/vda1 is played by the temporary file
            written.append(device)
            write_gap(str(self.device), frame)
        with patch.object(storage_worker, 'inventory', return_value=snapshot), \
                patch.object(storage_worker, 'live_source', return_value=''), \
                patch.object(storage_worker, 'write_gap', side_effect=write_device), \
                patch.object(storage_worker, 'gap_free', return_value=True):
            self.assertTrue(storage_worker.mark({'record': record, 'revert': {'kind': 'partition', 'device': '/dev/vda1'}})['marked'])
            with self.assertRaises(ValidationError):
                storage_worker.mark({'record': record, 'revert': {'kind': 'partition', 'device': '/dev/vda2'}})
        self.assertEqual(written, ['/dev/vda1'])
        self.assertEqual(preview_record.decode_gap(storage_worker.read_gap(str(self.device)))['id'], 'a1b2c3')

    def test_mark_file_writes_sidecar_inside_the_mounted_medium_only(self):
        preview = patch.object(storage_worker, 'PREVIEW', Path(self.directory.name) / 'preview')
        preview.start()
        self.addCleanup(preview.stop)
        folder = storage_worker.PREVIEW / 'media' / 'AGIOS-PREVIEW'
        folder.mkdir(parents=True)
        request = {'record': sample_record(), 'revert': {'kind': 'file', 'folder': '/etc'}}
        with patch.object(storage_worker.os.path, 'ismount', return_value=False):
            with self.assertRaises(ValidationError):
                storage_worker.mark(request)
        with patch.object(storage_worker.os.path, 'ismount', return_value=True):
            storage_worker.mark(request)
        self.assertEqual(json.loads((folder / 'preview.json').read_text())['id'], 'a1b2c3')
        shutil.rmtree(folder)
        (storage_worker.PREVIEW / 'media' / 'AGIOS-PREVIEW').symlink_to(self.directory.name)
        with patch.object(storage_worker.os.path, 'ismount', return_value=True):
            with self.assertRaises(ValidationError):
                storage_worker.mark(request)


class UndoTests(unittest.TestCase):
    def layout(self, before_fstype='ntfs'):
        disk = {'path': '/dev/sda', 'partitions': [
            {'path': '/dev/sda1', 'start': 2048, 'size': 100 * 2**20, 'fstype': 'vfat', 'mounted': False},
            {'path': '/dev/sda2', 'start': 206848, 'size': 20 * GIB, 'fstype': before_fstype, 'mounted': False},
            {'path': '/dev/sda3', 'start': 206848 + 20 * GIB // 512, 'size': 30 * GIB, 'partlabel': 'AGIOS-PREVIEW',
             'mounted': False}]}
        return disk, disk['partitions'][2]

    def entry(self, **storage):
        return {'kind': 'partition', 'record': {'storage': {'kind': 'shrink', 'shrunk_start': 206848,
                                                            'original_end': 206848 + 45 * GIB // 512 - 1,
                                                            'fstype': 'ntfs', **storage}}}

    def test_shrink_undo_derived_from_current_layout(self):
        disk, part = self.layout()
        state = storage_worker.undo_state(disk, part, self.entry())
        self.assertEqual((state['kind'], state['shrunk'], state['number']), ('shrink', '/dev/sda2', 2))

    def test_forged_shrink_boundary_falls_back_to_deleting_the_preview_only(self):
        disk, part = self.layout()
        for storage in ({'shrunk_start': 2048}, {'original_end': 10**12}, {'original_end': 206848},
                        {'fstype': 'ext4'}):
            state = storage_worker.undo_state(disk, part, self.entry(**storage))
            self.assertEqual(state, {'kind': 'partition', 'disk': '/dev/sda', 'device': '/dev/sda3'}, storage)

    def test_erase_is_kept_for_undo_but_cleaned_up_on_remove(self):
        disk, part = self.layout()
        entry = {'kind': 'partition', 'record': {'storage': {'kind': 'erase'}}}
        self.assertEqual(storage_worker.undo_state(disk, part, entry)['kind'], 'erase')
        self.assertEqual(storage_worker.undo_state(disk, part, entry, remove=True)['kind'], 'partition')

    def test_file_undo_is_the_preview_folder_of_the_media_mount(self):
        disk, part = self.layout()
        state = storage_worker.undo_state(disk, part, {'kind': 'file', 'record': None})
        self.assertEqual(Path(state['folder']), storage_worker.PREVIEW / 'media' / 'AGIOS-PREVIEW')


class MountTests(unittest.TestCase):
    def test_looking_at_a_medium_is_read_only_without_setuid_or_devices(self):
        calls = []
        def run(args, **kw):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0)
        with tempfile.TemporaryDirectory() as directory, patch.object(storage_worker.subprocess, 'run', run):
            self.assertTrue(storage_worker.read_only_mount('/dev/sdb1', 'ext4', Path(directory) / 'scan'))
        options = calls[-1][calls[-1].index('-o') + 1].split(',')
        for option in ('ro', 'noload', 'nosuid', 'nodev', 'noexec'):
            self.assertIn(option, options)


@unittest.skipUnless(shutil.which('qemu-img'), 'qemu-img is not installed')
class ImageTests(unittest.TestCase):
    def test_backing_file_and_data_file_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            plain, overlay, external = (Path(directory) / name for name in ('plain.qcow2', 'overlay.qcow2', 'external.qcow2'))
            subprocess.run(['qemu-img', 'create', '-q', '-f', 'qcow2', str(plain), '1M'], check=True)
            storage_worker.check_image(plain)
            subprocess.run(['qemu-img', 'create', '-q', '-f', 'qcow2', '-F', 'qcow2', '-b', str(plain), str(overlay)], check=True)
            with self.assertRaises(ValidationError):
                storage_worker.check_image(overlay)
            subprocess.run(['qemu-img', 'create', '-q', '-f', 'qcow2', '-o', f'data_file={directory}/data.raw',
                            str(external), '1M'], check=True)
            with self.assertRaises(ValidationError):
                storage_worker.check_image(external)


class ScanTests(unittest.TestCase):
    def test_scan_skips_mounted_and_live_partitions(self):
        snapshot = {'disks': [{'path': '/dev/sda', 'model': 'Disk', 'partitions': [
            {'path': '/dev/sda1', 'partlabel': 'AGIOS-PREVIEW', 'mounted': False, 'size': 1, 'fstype': None},
            {'path': '/dev/sda2', 'partlabel': 'AGIOS-PREVIEW', 'mounted': True, 'size': 1, 'fstype': None},
            {'path': '/dev/sda3', 'partlabel': 'DATA', 'mounted': False, 'size': 1, 'fstype': 'exfat'},
            {'path': '/dev/sda4', 'partlabel': 'LIVE', 'mounted': False, 'size': 1, 'fstype': 'vfat'},
            {'path': '/dev/sda5', 'partlabel': 'SWAP', 'mounted': False, 'size': 1, 'fstype': 'swap'}]}]}
        looked = []
        with patch.object(storage_worker, 'inventory', return_value=snapshot), \
                patch.object(storage_worker, 'read_command', return_value='/dev/sda4\n'), \
                patch.object(storage_worker, 'partition_entry', side_effect=lambda d, p: looked.append(p['path']) or {'id': 'partition:' + p['path']}), \
                patch.object(storage_worker, 'file_entry', side_effect=lambda d, p: looked.append(p['path']) or None):
            found = storage_worker.scan({})['found']
        self.assertEqual(looked, ['/dev/sda1', '/dev/sda3'])
        self.assertEqual([f['id'] for f in found], ['partition:/dev/sda1'])


if __name__ == '__main__':
    unittest.main()
