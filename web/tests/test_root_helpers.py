"""Root helpers (storage_worker, finalize_worker) against a hostile caller.

The website runs as user agi; everything it sends to the helpers, including the
revert records it keeps in session.json, is treated as forged here. Nothing in
these tests runs a real disk command: inventories are fixtures and every command
runner is replaced by a recorder.
"""
import copy
import io
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: F401 (sets the engine import path)
import deployment
import finalize_worker
import storage_worker
from controller import DemoProvider
from domain import ValidationError

GIB = 2**30
S = 512


def part(path, start, size, fstype=None, partlabel=None, mounted=False, label=None):
    return {'path': path, 'start': start, 'size': size, 'fstype': fstype, 'partlabel': partlabel,
            'label': label, 'mounted': mounted}


def fixture():
    """sda: target with Windows and a shrink-made preview; sdb: the Live USB stick;
    sdc: a data disk with a file-capable partition and an older preview partition."""
    win_end = 2048 + 100 * GIB // S - 1
    disks = [
        {'path': '/dev/sda', 'size': 256 * GIB, 'pttype': 'gpt', 'fstype': None, 'ro': False, 'serial': 'AGIOS_TARGET',
         'eligible': True, 'reason': '', 'fingerprint': 'fp-sda', 'model': 'SSD', 'tran': 'nvme',
         'partitions': [part('/dev/sda1', 2048, 60 * GIB, 'ntfs', 'Basic data partition'),
                        part('/dev/sda2', 2048 + 60 * GIB // S, 40 * GIB, None, 'AGIOS-PREVIEW')]},
        {'path': '/dev/sdb', 'size': 16 * GIB, 'pttype': 'dos', 'fstype': 'iso9660', 'ro': False, 'serial': 'USB',
         'eligible': False, 'reason': 'busy', 'fingerprint': 'fp-sdb', 'model': 'Stick', 'tran': 'usb',
         'partitions': [part('/dev/sdb1', 64, 2 * GIB, 'iso9660', None, mounted=True)]},
        {'path': '/dev/sdc', 'size': 128 * GIB, 'pttype': 'gpt', 'fstype': None, 'ro': False, 'serial': 'DATA',
         'eligible': True, 'reason': '', 'fingerprint': 'fp-sdc', 'model': 'HDD', 'tran': 'sata',
         'partitions': [part('/dev/sdc1', 2048, 64 * GIB, 'ext4', 'data'),
                        part('/dev/sdc2', 2048 + 64 * GIB // S, 16 * GIB, None, 'AGIOS-PREVIEW')]},
    ]
    assert win_end  # documents the layout: sda1 was shrunk from 100 GiB to 60 GiB
    return {'live': True, 'firmware': 'uefi', 'disks': disks, 'hardware': {}}


ORIGINAL_END = 2048 + 100 * GIB // S - 1
PREVIEW = storage_worker.PREVIEW
VALID_STATES = {
    'ram': {'kind': 'ram', 'device': '/dev/zram0', 'mount': str(PREVIEW / 'ram')},
    'file': {'kind': 'file', 'device': '/dev/sdc1', 'mount': str(PREVIEW / 'media'), 'folder': str(PREVIEW / 'media/AGIOS-PREVIEW')},
    'partition': {'kind': 'partition', 'disk': '/dev/sdc', 'device': '/dev/sdc2', 'backup': str(PREVIEW / 'sdc.gpt')},
    'shrink': {'kind': 'shrink', 'disk': '/dev/sda', 'device': '/dev/sda2', 'shrunk': '/dev/sda1', 'fstype': 'ntfs',
               'number': 1, 'original_end': ORIGINAL_END, 'backup': str(PREVIEW / 'sda.gpt')},
    'erase': {'kind': 'erase', 'disk': '/dev/sda', 'device': '/dev/sda1'},
}
VALID_OPTIONS = ['ram', 'file:/dev/sdc1', 'part:/dev/sda:209717248', 'part:/dev/sdc:167774208', 'shrink:/dev/sda1', 'erase:/dev/sda']


class Environment:
    """Patches the helpers onto the fixture: Live, root, the USB stick as boot medium."""

    def __init__(self, snapshot=None):
        self.snapshot = snapshot or fixture()
        self.patches = [
            patch.object(storage_worker, 'inventory', side_effect=lambda: copy.deepcopy(self.snapshot)),
            patch.object(finalize_worker, 'inventory', side_effect=lambda: copy.deepcopy(self.snapshot)),
            patch.object(storage_worker, 'live_source', return_value='/dev/sdb1'),
            patch.object(storage_worker, 'mount_source', return_value=None),
        ]

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()


class RequestSchemaTests(unittest.TestCase):
    def test_unknown_or_extra_keys_rejected(self):
        for request in ({}, [], 'probe', {'op': 'format'}, {'op': 'revert'},
                        {'op': 'revert', 'state': {}, 'shell': 'x'},
                        {'op': 'probe', 'needed': 1, 'target': '/dev/sda', 'vm_memory': 0, 'extra': 1}):
            with self.assertRaises(ValidationError):
                storage_worker.checked_request(request)

    def test_data_root_from_the_caller_is_ignored(self):
        request = storage_worker.checked_request({'op': 'revert', 'state': {}, 'data_root': '/etc'})
        self.assertNotIn('data_root', request)
        self.assertEqual(storage_worker.PREVIEW, Path('/run/agi-os-preview'))

    def test_numbers_are_strict(self):
        base = {'needed': 8 * GIB, 'target': '/dev/sda', 'vm_memory': 4 * GIB}
        for key, value in (('needed', True), ('needed', -1), ('needed', 0), ('needed', '8'), ('needed', 2**70),
                           ('needed', 1.5), ('vm_memory', None), ('target', '/etc/passwd'), ('target', '/dev/sda\n'),
                           ('target', '/dev/../etc'), ('compression', float('nan')), ('compression', float('inf')),
                           ('compression', 0.1), ('compression', '1.3'), ('sparse', -1), ('sparse', 9 * GIB),
                           ('sparse', True)):
            with self.assertRaises(ValidationError, msg=(key, value)):
                storage_worker.sizing({**base, key: value})
        self.assertEqual(storage_worker.sizing(base), (8 * GIB, '/dev/sda', 4 * GIB, storage_worker.COMPRESSION))

    def test_partition_numbers(self):
        number = storage_worker.partition_number
        self.assertEqual(number('/dev/sda', '/dev/sda3'), 3)
        self.assertEqual(number('/dev/nvme0n1', '/dev/nvme0n1p12'), 12)
        for disk, device in (('/dev/sda', '/dev/sdab1'), ('/dev/sda', '/dev/sda'), ('/dev/sda', '/dev/sdb1'),
                             ('/dev/nvme0n1', '/dev/nvme0n12'), ('/dev/sda', '/dev/sdap1'), ('/dev/sda', '/dev/sda0')):
            with self.assertRaises(ValidationError, msg=device):
                number(disk, device)


class OptionTests(unittest.TestCase):
    def resolve(self, option, target='/dev/sda'):
        with Environment() as env:
            return storage_worker.resolve_option(option, target, env.snapshot)

    def test_forged_fields_are_ignored_devices_come_from_the_inventory(self):
        resolved = self.resolve({'id': 'file:/dev/sdc1', 'kind': 'file', 'device': '/dev/sda', 'fstype': 'ext4'})
        self.assertEqual(resolved, {'kind': 'file', 'device': '/dev/sdc1', 'fstype': 'ext4'})
        resolved = self.resolve({'id': 'shrink:/dev/sda1', 'kind': 'shrink', 'disk': '/dev/sdc', 'fstype': 'ext4'})
        self.assertEqual(resolved['disk'], '/dev/sda')
        self.assertEqual(resolved['fstype'], 'ntfs')

    def test_refused_locations(self):
        refused = [
            {'id': 'file:/dev/sda1'},             # a file on the target disk
            {'id': 'file:/dev/sdb1'},             # the Live medium
            {'id': 'file:/dev/sdc2'},             # no filesystem
            {'id': 'file:/dev/sdz1'},             # unknown
            {'id': 'part:/dev/sdb:2048'},         # free space on the Live stick
            {'id': 'part:/dev/sdc:x'},
            {'id': 'part:/etc:2048'},
            {'id': 'shrink:/dev/sdc1'},           # only the target is shrunk
            {'id': 'erase:/dev/sdc'},             # only the target is erased
            {'id': 'erase:/dev/sdb'},
            {'id': 'ram:/dev/sda'},
            {'id': 'file:/dev/sdc1', 'kind': 'erase'},  # kind contradicts the id
            {'id': 'wipe:/dev/sda'}, {'id': 5}, {}, 'ram', None,
        ]
        for option in refused:
            with self.assertRaises(ValidationError, msg=option):
                self.resolve(option)

    def test_target_must_stay_eligible(self):
        snapshot = fixture()
        snapshot['disks'][0]['eligible'] = False
        with Environment(snapshot):
            for option in ('erase:/dev/sda', 'shrink:/dev/sda1', 'part:/dev/sda:209717248'):
                with self.assertRaises(ValidationError, msg=option):
                    storage_worker.resolve_option({'id': option}, '/dev/sda', snapshot)

    def test_test_vm_refuses_other_targets(self):
        with tempfile.NamedTemporaryFile() as marker, patch.object(deployment, 'TEST_MARKER', Path(marker.name)):
            snapshot = deployment.restrict_test_targets(fixture())
        self.assertTrue(snapshot['disks'][0]['eligible'])
        self.assertFalse(snapshot['disks'][2]['eligible'])
        with self.assertRaises(ValidationError):
            storage_worker.resolve_option({'id': 'erase:/dev/sdc'}, '/dev/sdc', snapshot)


class RevertStateTests(unittest.TestCase):
    def check(self, state):
        with Environment() as env:
            return storage_worker.checked_state(state, env.snapshot)

    def test_valid_records_pass(self):
        for state in VALID_STATES.values():
            self.check(copy.deepcopy(state))

    def test_forged_records_rejected(self):
        forged = [
            {**VALID_STATES['ram'], 'device': '/dev/sda'},
            {**VALID_STATES['ram'], 'mount': '/'},
            {**VALID_STATES['file'], 'folder': '/etc'},
            {**VALID_STATES['file'], 'mount': '/home/agi'},
            {**VALID_STATES['file'], 'device': '/dev/sdb1'},       # mounted Live medium
            {**VALID_STATES['partition'], 'device': '/dev/sdc1'},  # user data, not a preview
            {**VALID_STATES['partition'], 'disk': '/dev/sda'},     # device on another disk
            {**VALID_STATES['partition'], 'disk': '/dev/sdb', 'device': '/dev/sdb1'},
            {**VALID_STATES['shrink'], 'original_end': ORIGINAL_END + 200 * GIB // S},  # past the disk end
            {**VALID_STATES['shrink'], 'number': 2},
            {**VALID_STATES['shrink'], 'shrunk': '/dev/sdc1', 'fstype': 'ext4'},
            {**VALID_STATES['shrink'], 'fstype': 'ext4'},
            {**VALID_STATES['shrink'], 'original_end': True},
            {**VALID_STATES['shrink'], 'original_end': 1000},  # before the preview partition
            {**VALID_STATES['partition'], 'extra': 1},
            {'kind': 'partition', 'disk': '/dev/sdc'},
            {'kind': 'format'}, [], None,
        ]
        for state in forged:
            with self.assertRaises(ValidationError, msg=state):
                self.check(state)

    def test_growing_back_never_swallows_a_neighbour(self):
        snapshot = fixture()
        # A partition the user created later between the shrunk one and its old end.
        snapshot['disks'][0]['partitions'].append(part('/dev/sda3', 2048 + 99 * GIB // S, GIB // 2, 'ext4', 'new'))
        with Environment(snapshot):
            with self.assertRaises(ValidationError):
                storage_worker.checked_state(copy.deepcopy(VALID_STATES['shrink']), snapshot)

    def test_mounted_preview_partition_is_not_deleted(self):
        snapshot = fixture()
        snapshot['disks'][2]['partitions'][1]['mounted'] = True
        with Environment(snapshot):
            with self.assertRaises(ValidationError):
                storage_worker.checked_state(copy.deepcopy(VALID_STATES['partition']), snapshot)


class SymlinkTests(unittest.TestCase):
    """Real files in a temporary directory stand in for the root-owned runtime directory."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, ignore_errors=True))
        self.outside = self.tmp / 'outside'
        self.outside.mkdir()
        (self.outside / 'keep').write_text('user data')

    def test_private_dir_refuses_symlinks_and_shared_directories(self):
        link = self.tmp / 'link'
        link.symlink_to(self.outside)
        with self.assertRaises(ValidationError):
            storage_worker.private_dir(link)
        shared = self.tmp / 'shared'
        shared.mkdir()
        shared.chmod(0o777)
        with self.assertRaises(ValidationError):
            storage_worker.private_dir(shared)
        fine = storage_worker.private_dir(self.tmp / 'a' / 'b')
        self.assertEqual(fine.stat().st_mode & 0o777, 0o755)

    def test_image_file_refuses_planted_links(self):
        media = self.tmp / 'media'
        media.mkdir()
        (media / 'AGIOS-PREVIEW').symlink_to(self.outside)
        with patch.object(storage_worker, 'sh') as sh:
            with self.assertRaises(ValidationError):
                storage_worker.image_file(media / 'AGIOS-PREVIEW', GIB)
            (media / 'AGIOS-PREVIEW').unlink()
            (media / 'AGIOS-PREVIEW').mkdir()
            (media / 'AGIOS-PREVIEW/preview.qcow2').symlink_to(self.outside / 'keep')
            with self.assertRaises(ValidationError):
                storage_worker.image_file(media / 'AGIOS-PREVIEW', GIB)
        sh.assert_not_called()

    def test_image_file_changes_owner_without_following_links(self):
        folder = self.tmp / 'AGIOS-PREVIEW'
        with patch.object(storage_worker, 'sh', side_effect=lambda args, **kw: Path(args[-2]).write_bytes(b'')), \
                patch.object(storage_worker, 'site_owner', return_value=(os.getuid(), os.getgid())), \
                patch.object(storage_worker.os, 'chown') as chown:
            image = storage_worker.image_file(folder, GIB)
        self.assertEqual(image, {'format': 'qcow2', 'path': str(folder / 'preview.qcow2')})
        self.assertTrue(all(call.kwargs == {'follow_symlinks': False} for call in chown.call_args_list))

    def test_file_revert_does_not_follow_a_planted_link(self):
        media = self.tmp / 'media'
        media.mkdir()
        (media / 'AGIOS-PREVIEW').symlink_to(self.outside)
        state = {'kind': 'file', 'device': '/dev/sdc1', 'mount': str(media), 'folder': str(media / 'AGIOS-PREVIEW')}
        with Environment(), patch.object(storage_worker, 'PREVIEW', self.tmp), \
                patch.object(storage_worker, 'mount_source', return_value='/dev/sdc1'), \
                patch.object(storage_worker, 'sh'), patch.object(storage_worker.subprocess, 'run'):
            result = storage_worker.revert({'state': state})
        self.assertTrue(result['reverted'])
        self.assertFalse((media / 'AGIOS-PREVIEW').exists())
        self.assertEqual((self.outside / 'keep').read_text(), 'user data')

    def test_file_revert_removes_only_the_preview_image(self):
        media = self.tmp / 'media'
        (media / 'AGIOS-PREVIEW').mkdir(parents=True)
        (media / 'AGIOS-PREVIEW/preview.qcow2').write_bytes(b'')
        (media / 'AGIOS-PREVIEW/notes.txt').write_text('user file')
        state = {'kind': 'file', 'device': '/dev/sdc1', 'mount': str(media), 'folder': str(media / 'AGIOS-PREVIEW')}
        with Environment(), patch.object(storage_worker, 'PREVIEW', self.tmp), \
                patch.object(storage_worker, 'mount_source', return_value='/dev/sdc1'), \
                patch.object(storage_worker, 'sh'), patch.object(storage_worker.subprocess, 'run'):
            storage_worker.revert({'state': state})
        self.assertFalse((media / 'AGIOS-PREVIEW/preview.qcow2').exists())
        self.assertEqual((media / 'AGIOS-PREVIEW/notes.txt').read_text(), 'user file')

    def test_file_revert_after_restart_mounts_the_checked_device_first(self):
        media = self.tmp / 'media'
        state = {'kind': 'file', 'device': '/dev/sdc1', 'mount': str(media), 'folder': str(media / 'AGIOS-PREVIEW')}
        calls = []
        with Environment(), patch.object(storage_worker, 'PREVIEW', self.tmp), \
                patch.object(storage_worker, 'sh', side_effect=lambda args, **kw: calls.append(args)), \
                patch.object(storage_worker.subprocess, 'run'):
            storage_worker.revert({'state': state})
        mount = next(c for c in calls if c[0] == 'mount')
        self.assertIn('nosuid', mount[2])
        self.assertEqual(mount[-2:], ['/dev/sdc1', str(media)])


class PrepareTests(unittest.TestCase):
    """prepare runs on the resolved option only; recorded commands show what would touch disks."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, ignore_errors=True))
        self.calls = []

    def sh(self, args, **kw):
        self.calls.append(args)
        if args[0] == 'qemu-img':
            Path(args[-2]).write_bytes(b'')
        return ''

    def prepare(self, option, snapshot=None):
        request = {'op': 'prepare', 'option': option, 'needed': 8 * GIB, 'target': '/dev/sda', 'vm_memory': 4 * GIB}
        stat = os.statvfs(self.tmp)
        with Environment(snapshot), patch.object(storage_worker, 'PREVIEW', self.tmp), \
                patch.object(storage_worker, 'sh', side_effect=self.sh), \
                patch.object(storage_worker, 'site_owner', return_value=(os.getuid(), os.getgid())), \
                patch.object(storage_worker.os, 'statvfs', return_value=type(stat)((0, 4096, 0, 0, 10**9, 0, 0, 0, 0, 255))):
            return storage_worker.prepare(request)

    def test_file_option_mounts_the_inventory_device_without_suid(self):
        result = self.prepare({'id': 'file:/dev/sdc1', 'kind': 'file', 'device': '/dev/sda1', 'fstype': 'ntfs'})
        mount = next(c for c in self.calls if c[0] == 'mount')
        self.assertEqual(mount[-2:], ['/dev/sdc1', str(self.tmp / 'media')])
        self.assertEqual(mount[2], 'noatime,nosuid,nodev,noexec')
        self.assertEqual(result['revert'], {'kind': 'file', 'device': '/dev/sdc1', 'mount': str(self.tmp / 'media'),
                                            'folder': str(self.tmp / 'media/AGIOS-PREVIEW')})
        self.assertEqual(result['image']['path'], str(self.tmp / 'media/AGIOS-PREVIEW/preview.qcow2'))

    def test_forged_erase_never_runs_a_command(self):
        for option in ({'id': 'erase:/dev/sdc', 'kind': 'erase', 'disk': '/dev/sdc'},
                       {'id': 'erase:/dev/sda', 'kind': 'erase', 'disk': '/dev/sdb'}):
            try:
                self.prepare(option)
            except (ValidationError, StopIteration, IndexError):
                pass
        erased = [c for c in self.calls if c[:2] == ['sgdisk', '--zap-all']]
        self.assertEqual(erased, [['sgdisk', '--zap-all', '/dev/sda']])  # the second request erases the target only

    def test_signature_less_disk_is_not_repartitioned(self):
        snapshot = fixture()
        snapshot['disks'][2].update(pttype=None, partitions=[])
        with patch.object(storage_worker, 'looks_blank', return_value=False):
            with self.assertRaises(ValidationError):
                self.prepare({'id': 'part:/dev/sdc:2048'}, snapshot)
        self.assertFalse([c for c in self.calls if c[0] == 'sgdisk'])


class RestartOperationTests(unittest.TestCase):
    """scan / adopt / remove / mark (CMP-119) behind the same checks."""

    def test_schemas(self):
        for request in ({'op': 'scan', 'extra': 1}, {'op': 'adopt'}, {'op': 'remove', 'id': 'x', 'state': {}},
                        {'op': 'mark', 'record': {}}):
            with self.assertRaises(ValidationError, msg=request):
                storage_worker.checked_request(request)
        for request in ({'op': 'scan'}, {'op': 'adopt', 'id': 'partition:/dev/sda2'}, {'op': 'remove', 'id': 'file:/dev/sdc1'},
                        {'op': 'mark', 'record': {}, 'revert': {}}):
            storage_worker.checked_request(request)

    def test_found_ids_must_be_text(self):
        with Environment():
            for found in (None, 5, ['partition:/dev/sda2'], {'id': 'x'}):
                with self.assertRaises(ValidationError):
                    storage_worker.locate(found)

    def test_mark_writes_only_into_a_free_preview_partition(self):
        from test_preview_record import sample_record
        with Environment(), patch.object(storage_worker, 'gap_free', return_value=True), \
                patch.object(storage_worker, 'write_gap') as write:
            for revert in ({'kind': 'partition', 'device': '/dev/sdc1'}, {'kind': 'shrink', 'device': '/dev/sdb1'},
                           {'kind': 'erase', 'device': '/etc/passwd'}, {'kind': 'partition'}, [], 'partition', None):
                with self.assertRaises(ValidationError, msg=revert):
                    storage_worker.mark({'record': sample_record(), 'revert': revert})
            write.assert_not_called()
            storage_worker.mark({'record': sample_record(), 'revert': {'kind': 'partition', 'device': '/dev/sdc2'}})
        self.assertEqual(write.call_args.args[0], '/dev/sdc2')

    def test_removing_a_found_file_preview_keeps_other_user_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'media/AGIOS-PREVIEW'
            folder.mkdir(parents=True)
            for name in ('preview.qcow2', 'preview.json', 'holiday.jpg'):
                (folder / name).write_bytes(b'x')
            state = {'kind': 'file', 'device': '/dev/sdc1', 'mount': str(root / 'media'), 'folder': str(folder)}
            with Environment(), patch.object(storage_worker, 'PREVIEW', root), \
                    patch.object(storage_worker, 'mount_source', return_value='/dev/sdc1'), \
                    patch.object(storage_worker, 'sh'), patch.object(storage_worker.subprocess, 'run'):
                storage_worker.revert({'state': state})
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['holiday.jpg'])


class BlankDiskTests(unittest.TestCase):
    def test_signature_less_data_is_not_free_space(self):
        with tempfile.NamedTemporaryFile() as image:
            image.write(b'\0' * storage_worker.BLANK_PROBE)
            image.flush()
            disk = {'path': image.name, 'size': 16 * GIB, 'pttype': None, 'fstype': None}
            self.assertEqual(len(storage_worker.free_regions(disk)), 1)
            image.seek(4096)
            image.write(os.urandom(512))  # e.g. a VeraCrypt header: no signature, not empty
            image.flush()
            self.assertEqual(storage_worker.free_regions(disk), [])
        self.assertFalse(storage_worker.looks_blank('/nonexistent/device'))


class FinalizeImageTests(unittest.TestCase):
    def request(self, image):
        config = DemoProvider().reply('', [])['configuration']
        config['disk'] = '/dev/sda'
        return {'target': '/dev/sda', 'fingerprint': 'fp-sda', 'configuration': config, 'passphrase': '',
                'image': image, 'layout': 'alongside', 'confirmation': '/dev/sda'}

    def check(self, image):
        with Environment(), patch.object(finalize_worker.os, 'geteuid', return_value=0), \
                patch.object(finalize_worker, 'live_environment', return_value=True):
            request = self.request(image)
            finalize_worker.checked_request(request)
            return request['image']

    def test_preview_partitions_are_accepted(self):
        self.assertTrue(self.check({'format': 'raw', 'path': '/dev/sda2'})['on_target'])
        self.assertFalse(self.check({'format': 'raw', 'path': '/dev/sdc2'})['on_target'])

    def test_anything_else_is_refused(self):
        for image in ({'format': 'raw', 'path': '/dev/sda1'}, {'format': 'raw', 'path': '/dev/sdb1'},
                      {'format': 'raw', 'path': '/dev/sda'}, {'format': 'raw', 'path': '/dev/sdab2'},
                      {'format': 'qcow2', 'path': '/etc/shadow'},
                      {'format': 'qcow2', 'path': '/var/lib/agi-os/preview/ram/preview.qcow2'},
                      {'format': 'qcow2', 'path': str(PREVIEW / 'ram/../media/x.qcow2')},
                      {'format': 'vmdk', 'path': '/dev/sda2'}, {'format': 'raw'}, {'format': 'raw', 'path': 5},
                      {'format': 'raw', 'path': '/dev/sda2', 'on_target': True}, 'raw', None):
            with self.assertRaises(ValidationError, msg=image):
                self.check(image)

    def test_qcow2_inside_the_prepared_mount_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(os.path.realpath(tmp))
            (root / 'ram').mkdir()
            (root / 'ram/preview.qcow2').write_bytes(b'')
            with patch.object(storage_worker, 'PREVIEW', root):
                image = self.check({'format': 'qcow2', 'path': str(root / 'ram/preview.qcow2')})
                self.assertFalse(image['on_target'])
                (root / 'ram/preview.qcow2').unlink()
                (root / 'ram/preview.qcow2').symlink_to('/etc/hostname')
                with self.assertRaises(ValidationError):
                    self.check({'format': 'qcow2', 'path': str(root / 'ram/preview.qcow2')})

    def test_preview_filesystems_are_mounted_without_trust(self):
        calls = []
        class Runner:
            def run(self, args, **kw):
                calls.append(args)
                return ''
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / 'var/lib/agi-os'
            record.mkdir(parents=True)
            (record / 'installation.json').write_text('{}')
            finalize_worker.read_record(Runner(), '/dev/mapper/x', Path(tmp))
        self.assertEqual(calls[0][:3], ['mount', '-o', 'ro,nosuid,nodev,noexec'])


# ---- Fuzzing: mutated requests must be refused cleanly or resolve to allowed devices only ----

POOL = [None, True, False, 0, -1, 1, 2**70, 1.5, float('nan'), float('inf'), '', 'x', ' ', '\n', '../../etc',
        '/', '/etc', '/etc/shadow', '/dev/sda', '/dev/sda1', '/dev/sda2', '/dev/sdab2', '/dev/sdb', '/dev/sdb1',
        '/dev/sdc', '/dev/sdc1', '/dev/sdc2', '/dev/zram0', '/dev/zram0 ', '/dev/sda1; reboot', '/dev/sda\n',
        'ram', 'file:/dev/sda1', 'file:/dev/sdb1', 'part:/dev/sdb:2048', 'part:/dev/sda:-5', 'erase:/dev/sdc',
        'erase:/dev/sdb', 'shrink:/dev/sdc1', 'shrink:/dev/sda2', 'partition', 'shrink', 'erase', 'file',
        str(PREVIEW / 'media'), str(PREVIEW / 'ram'), [], {}, [1, 2], {'id': 'erase:/dev/sdb'}]
ALLOWED = {  # what a resolved option or a checked state may ever point at in the fixture
    'file': {'/dev/sdc1'}, 'partition': {'/dev/sda', '/dev/sdc'}, 'shrink': {'/dev/sda1'}, 'erase': {'/dev/sda'},
    'preview': {'/dev/sda2', '/dev/sdc2'},
    'file-state': {'/dev/sda1', '/dev/sdc1'},  # revert removes only AGIOS-PREVIEW/preview.qcow2 there
}


def mutate(value, rng, depth=0):
    if isinstance(value, dict) and value and rng.random() < 0.8:
        value = dict(value)
        key = rng.choice(sorted(value))
        action = rng.random()
        if action < 0.1:
            del value[key]
        elif action < 0.15:
            value['extra'] = rng.choice(POOL)
        else:
            value[key] = mutate(value[key], rng, depth + 1)
        return value
    return copy.deepcopy(rng.choice(POOL))


class FuzzTests(unittest.TestCase):
    ROUNDS = 3000

    def test_storage_requests(self):
        rng = random.Random(135)
        bases = ([{'op': 'probe', 'needed': 8 * GIB, 'target': '/dev/sda', 'vm_memory': 4 * GIB, 'compression': 1.3}]
                 + [{'op': 'prepare', 'option': {'id': o}, 'needed': 8 * GIB, 'target': '/dev/sda', 'vm_memory': 4 * GIB}
                    for o in VALID_OPTIONS]
                 + [{'op': 'revert', 'state': s} for s in VALID_STATES.values()])
        accepted = 0
        with Environment() as env:
            for _ in range(self.ROUNDS):
                request = mutate(rng.choice(bases), rng)
                try:
                    checked = storage_worker.checked_request(request)
                    if checked['op'] == 'revert':
                        state = storage_worker.checked_state(checked['state'], copy.deepcopy(env.snapshot))
                        self.assert_state_allowed(state)
                    else:
                        needed, target, *_ = storage_worker.sizing(checked)
                        if checked['op'] == 'prepare':
                            option = storage_worker.resolve_option(checked['option'], target, copy.deepcopy(env.snapshot))
                            self.assert_option_allowed(option, target)
                    accepted += 1
                except ValidationError:
                    pass
                except Exception as exc:  # anything else is a validation gap
                    self.fail(f'{type(exc).__name__}: {exc} for {request!r}')
        self.assertGreater(accepted, 100)  # the fuzzer also exercises the accepting paths

    def assert_option_allowed(self, option, target):
        kind = option['kind']
        if kind == 'ram':
            return
        device = option.get('device') or option.get('disk')
        self.assertIn(device, ALLOWED[kind], option)
        if kind in ('shrink', 'erase'):
            self.assertEqual(target, '/dev/sda')

    def assert_state_allowed(self, state):
        kind = state['kind']
        if kind == 'ram':
            self.assertRegex(state['device'], r'^/dev/zram\d+$')
            self.assertEqual(state['mount'], str(PREVIEW / 'ram'))
        elif kind == 'file':
            self.assertEqual(state['mount'], str(PREVIEW / 'media'))
            self.assertIn(state['device'], ALLOWED['file-state'])
        elif kind in ('partition', 'shrink'):
            self.assertIn(state['device'], ALLOWED['preview'])
            if kind == 'shrink':
                self.assertEqual(state['shrunk'], '/dev/sda1')

    def test_storage_main_always_answers_one_json_line(self):
        rng = random.Random(1350)
        inputs = ['', 'null', '[]', '"probe"', '{', '{"op": "probe"}', '{"op": "revert", "state": null}',
                  '1e999', '{"op": {"op": "probe"}}', '[' * 5000 + ']' * 5000]
        inputs += [json.dumps(mutate({'op': 'revert', 'state': VALID_STATES['partition']}, rng)) for _ in range(200)]
        with Environment(), patch.object(storage_worker.os, 'geteuid', return_value=0), \
                patch.object(storage_worker, 'live_environment', return_value=True), \
                patch.object(storage_worker, 'sh', side_effect=AssertionError('no command may run')), \
                patch.object(storage_worker, 'delete_partition', side_effect=lambda *a: None), \
                patch.object(storage_worker.subprocess, 'run', side_effect=AssertionError('no command may run')):
            for line in inputs:
                out = io.StringIO()
                with patch.object(sys, 'stdin', io.StringIO(line + '\n')), patch.object(sys, 'stdout', out):
                    code = storage_worker.main()
                answer = json.loads(out.getvalue())
                self.assertEqual(len(answer), 1)
                if 'error' in answer:
                    self.assertEqual(code, 1)
                    self.assertNotIn('no command may run', answer['error'])
                else:  # only a fully valid preview-partition record gets through, and it deletes that one
                    self.assertTrue(answer['result']['reverted'])

    def test_mark_requests(self):
        from test_preview_record import sample_record
        rng = random.Random(1352)
        record = sample_record()
        written = []
        with Environment(), patch.object(storage_worker, 'gap_free', return_value=True), \
                patch.object(storage_worker, 'write_gap', side_effect=lambda device, frame: written.append(device)), \
                patch.object(storage_worker.os.path, 'ismount', return_value=False):
            for _ in range(self.ROUNDS // 3):
                state = mutate(rng.choice(list(VALID_STATES.values())), rng)
                try:
                    storage_worker.mark({'record': record, 'revert': state})
                except ValidationError:
                    pass
                except Exception as exc:
                    self.fail(f'{type(exc).__name__}: {exc} for {state!r}')
        self.assertTrue(written)
        self.assertLessEqual(set(written), ALLOWED['preview'])

    def test_finalize_requests(self):
        rng = random.Random(1351)
        config = DemoProvider().reply('', [])['configuration']
        config['disk'] = '/dev/sda'
        base = {'target': '/dev/sda', 'fingerprint': 'fp-sda', 'configuration': config, 'passphrase': '',
                'image': {'format': 'raw', 'path': '/dev/sda2'}, 'layout': 'alongside', 'confirmation': '/dev/sda'}
        with Environment(), patch.object(finalize_worker.os, 'geteuid', return_value=0), \
                patch.object(finalize_worker, 'live_environment', return_value=True):
            for _ in range(self.ROUNDS):
                request = mutate(base, rng)
                try:
                    finalize_worker.checked_request(request)
                    self.assertIn(request['image']['path'], ALLOWED['preview'])
                    self.assertEqual(request['target'], '/dev/sda')
                except ValidationError:
                    pass
                except Exception as exc:
                    self.fail(f'{type(exc).__name__}: {exc} for {request!r}')


if __name__ == '__main__':
    unittest.main()
