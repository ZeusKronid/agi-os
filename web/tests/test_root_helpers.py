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
import subprocess
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
from domain import Configuration, ValidationError

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
            patch.object(storage_worker, 'hibernated', return_value=False),
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

    def test_parents_inside_the_runtime_directory_are_0755_under_a_strict_umask(self):
        root = self.tmp / 'run-preview'
        old = os.umask(0o077)
        try:
            with patch.object(storage_worker, 'PREVIEW', root):
                storage_worker.private_dir(root / 'scan')
        finally:
            os.umask(old)
        self.assertEqual(root.stat().st_mode & 0o777, 0o755)
        self.assertEqual((root / 'scan').stat().st_mode & 0o777, 0o755)

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
                'image': image, 'layout': 'alongside', 'confirmation': '/dev/sda', 'enroll_keys': False}

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



class WindowsSafetyTests(unittest.TestCase):
    """CMP-151: a hibernated (Fast Startup) or BitLocker Windows is never written or resized."""

    def probe(self, snapshot, state):
        with Environment(snapshot), patch.object(storage_worker, 'hibernated', return_value=state), \
                patch.object(storage_worker, 'mem_available', return_value=4 * GIB), \
                patch.object(storage_worker, 'fs_free', return_value=50 * GIB), \
                patch.object(storage_worker, 'shrink_room', return_value=30 * GIB), \
                patch.object(storage_worker, 'free_regions', return_value=[]):
            return {o['id']: o for o in storage_worker.probe({'needed': 8 * GIB, 'target': '/dev/sda', 'vm_memory': 4 * GIB})['options']}

    def test_hibernated_windows_is_offered_neither_for_shrinking_nor_for_a_file(self):
        snapshot = fixture()
        snapshot['disks'][2]['partitions'][0].update(fstype='ntfs')  # a Windows data disk
        options = self.probe(snapshot, True)
        for option_id in ('shrink:/dev/sda1', 'file:/dev/sdc1'):
            option = options[option_id]
            self.assertFalse(option['fits'], option_id)
            self.assertIn('Fast Startup', option['blocked'])
            self.assertEqual(option['detail'], option['blocked'])
        self.assertTrue(self.probe(snapshot, False)['shrink:/dev/sda1']['fits'])
        self.assertNotIn('blocked', self.probe(snapshot, False)['file:/dev/sdc1'])

    def test_unreadable_windows_is_left_alone(self):
        self.assertIn('could not be checked', self.probe(fixture(), None)['shrink:/dev/sda1']['blocked'])

    def test_bitlocker_volume_is_explained_not_hidden(self):
        snapshot = fixture()
        snapshot['disks'][0]['partitions'][0].update(fstype='BitLocker')
        option = self.probe(snapshot, False)['shrink:/dev/sda1']
        self.assertFalse(option['fits'])
        self.assertIn('BitLocker', option['blocked'])

    def test_forged_choice_of_a_blocked_volume_is_refused(self):
        with Environment() as env, patch.object(storage_worker, 'hibernated', return_value=True):
            for option in ({'id': 'shrink:/dev/sda1'}, {'id': 'file:/dev/sdc1'}):
                env.snapshot['disks'][2]['partitions'][0]['fstype'] = 'ntfs'
                with self.assertRaises(ValidationError) as caught:
                    storage_worker.resolve_option(option, '/dev/sda', env.snapshot)
                self.assertIn('Fast Startup', str(caught.exception))

    def test_hiberfil_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            part = {'path': '/dev/sda3', 'fstype': 'ntfs', 'mounted': False}
            with patch.object(storage_worker, 'PREVIEW', root), \
                    patch.object(storage_worker, 'read_only_mount', return_value=True), \
                    patch.object(storage_worker.subprocess, 'run'):
                self.assertFalse(storage_worker.hibernated(part))  # no hiberfil.sys at all
                (root / 'check').mkdir()
                for head, state in ((b'HIBR' + b'\0' * 60, True), (b'hibr' + b'\0' * 60, True),
                                    (b'\0' * 64, False), (b'wake' + b'\0' * 60, False)):
                    (root / 'check/hiberfil.sys').write_bytes(head)
                    self.assertEqual(storage_worker.hibernated(part), state, head[:4])
            with patch.object(storage_worker, 'read_only_mount', return_value=False):
                self.assertIsNone(storage_worker.hibernated(part))



class DualBootFinalizeTests(unittest.TestCase):
    """CMP-151: finalizing next to Windows on UEFI shares its ESP and keeps its partitions."""

    ESP, WINDOWS, PREVIEW_PART = '/dev/vda1', '/dev/vda2', '/dev/vda3'
    BASE = 60 * GIB // S

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(tmp, ignore_errors=True))
        self.tmp, self.calls, self.promoted = tmp, [], False
        self.esp_guid = 'C12A7328-F81F-11D2-BA4B-00A0C93EC93B'
        self.basic = 'EBD0A0A2-B9E5-4433-87C0-68B6B72699C7'

    def table(self):
        parts = [{'node': self.ESP, 'start': 2048, 'size': 100 * 2**20 // S, 'type': self.esp_guid, 'uuid': 'E1'},
                 {'node': self.WINDOWS, 'start': 2048 + 100 * 2**20 // S, 'size': 50 * GIB // S, 'type': self.basic, 'uuid': 'W1'}]
        if self.promoted:
            parts += [{'node': '/dev/vda4', 'start': self.BASE + 2048, 'size': GIB // S, 'type': 'BC13C2FF-59E6-4262-A352-B275FD779F9C', 'uuid': 'B1'},
                      {'node': '/dev/vda5', 'start': self.BASE + 2048 + GIB // S, 'size': 14 * GIB // S, 'type': '0FC63DAF-8483-4772-8E79-3D69D8477DE4', 'uuid': 'R1'}]
        else:
            parts.append({'node': self.PREVIEW_PART, 'start': self.BASE, 'size': 16 * GIB // S, 'type': '0FC63DAF-8483-4772-8E79-3D69D8477DE4',
                          'uuid': 'P1', 'name': 'AGIOS-PREVIEW'})
        return json.dumps({'partitiontable': {'label': 'gpt', 'firstlba': 2048, 'lastlba': 128 * GIB // S - 34, 'partitions': parts}})

    def run_command(self, args, **kw):
        self.calls.append(args)
        if args[0] == 'sfdisk':
            return self.table()
        if args[0] == 'sgdisk' and any(a.startswith('--new') for a in args):
            self.promoted = True
        if args[0] == 'blkid':
            return 'ESP-UUID\n'
        if args[0] == 'mount' and args[-1].endswith('/target'):
            root = Path(args[-1])
            (root / 'etc').mkdir(parents=True)
            (root / 'etc/fstab').write_text('UUID=R1 / ext4 rw 0 1\n')
            (root / 'boot/loader').mkdir(parents=True)
            (root / 'boot/loader/loader.conf').write_text('default agi-os.conf\ntimeout 3\n')
            (root / 'var/lib/agi-os').mkdir(parents=True)
        return ''

    def finalize(self, bootloader='systemd-boot', enroll=False, hibernated=False, fstype='ntfs'):
        config = Configuration.parse({**DemoProvider().reply('', [])['configuration'], 'disk': '/dev/vda',
                                      'bootloader': bootloader})
        disk = {'path': '/dev/vda', 'pttype': 'gpt', 'fingerprint': 'fp', 'partitions': [
            part(self.ESP, 2048, 100 * 2**20, 'vfat', 'EFI system partition'),
            part(self.WINDOWS, 2048 + 100 * 2**20 // S, 50 * GIB, fstype, 'Basic data partition'),
            part(self.PREVIEW_PART, self.BASE, 16 * GIB, None, 'AGIOS-PREVIEW')]}
        request = {'image': {'format': 'raw', 'path': self.PREVIEW_PART, 'on_target': True}, 'layout': 'alongside',
                   'passphrase': '', 'enroll_keys': enroll}
        record = {'id': 'preview', 'configuration': config.as_dict(), 'firmware': 'uefi', 'secure_boot': None}
        class Source:
            opened, partitions = False, [{'node': '/dev/nbd0p1', 'start': 2048, 'size': GIB // S, 'name': 'AGI-BOOT'},
                                         {'node': '/dev/nbd0p2', 'start': 2048 + GIB // S, 'size': 14 * GIB // S, 'name': 'AGI-ROOT'}]
            def __init__(self, *a): pass
            def attach(self): return self
            group = None
            def open_root(self, number, passphrase): return '/dev/nbd0p2', False
            def close_root(self): pass
            def detach(self): pass
        runner = type('R', (), {'run': lambda _, args, **kw: self.run_command(args, **kw)})()
        with patch.object(finalize_worker, 'checked_request', return_value=(config, disk)), \
                patch.object(finalize_worker, 'live_firmware', return_value='uefi'), \
                patch.object(finalize_worker.tempfile, 'mkdtemp', return_value=str(self.tmp)), \
                patch.object(finalize_worker, 'Source', Source), \
                patch.object(finalize_worker, 'read_record', return_value=record), \
                patch.object(finalize_worker, 'check_record'), \
                patch.object(finalize_worker, 'fit_drivers'), \
                patch.object(finalize_worker, 'inspect_esp', return_value=(90 * 2**20, True)), \
                patch.object(storage_worker, 'hibernated', return_value=hibernated), \
                patch.object(finalize_worker, 'emit') as emit:
            finalize_worker.finalize(request, runner)
        return record, emit

    def test_systemd_boot_shares_the_windows_esp(self):
        record, _ = self.finalize()
        new = next(c for c in self.calls if c[0] == 'sgdisk' and any(a.startswith('--new') for a in c))
        self.assertIn('--typecode=0:ea00', new)  # /boot becomes XBOOTLDR, not a second ESP
        self.assertNotIn('--typecode=0:ef00', new)
        target = self.tmp / 'target'
        self.assertIn(['mount', '-o', 'umask=0077', self.ESP, str(target / 'efi')], self.calls)
        self.assertFalse(any(c[0].startswith('mkfs') and self.ESP in c for c in self.calls))  # never formatted
        self.assertIn('bootctl', next(c for c in self.calls if 'bootctl' in c))
        bootctl = next(c for c in self.calls if 'bootctl' in c)
        self.assertEqual(bootctl[-3:], ['--esp-path=/efi', '--boot-path=/boot', 'install'])
        self.assertEqual((target / 'efi/loader/loader.conf').read_text(), 'default agi-os.conf\ntimeout 3\n')
        self.assertIn('UUID=ESP-UUID /efi vfat umask=0077 0 2', (target / 'etc/fstab').read_text())
        self.assertEqual(record['dual_boot'], {'esp': self.ESP, 'shared_esp': True, 'windows': True})
        umounts = [c[1] for c in self.calls if c[0] == 'umount']
        self.assertLess(umounts.index(str(target / 'efi')), umounts.index(str(target / 'boot')))

    def test_grub_keeps_its_own_esp_and_chainloads_windows(self):
        self.finalize(bootloader='grub')
        new = next(c for c in self.calls if c[0] == 'sgdisk' and any(a.startswith('--new') for a in c))
        self.assertIn('--typecode=0:ef00', new)
        entry = (self.tmp / 'target/etc/grub.d/35_agios_windows').read_text()
        self.assertIn('search --no-floppy --fs-uuid --set=root ESP-UUID', entry)
        self.assertIn('chainloader /EFI/Microsoft/Boot/bootmgfw.efi', entry)

    def test_hibernated_windows_stops_before_any_change(self):
        with self.assertRaises(ValidationError) as caught:
            self.finalize(hibernated=True)
        self.assertIn('Nothing was changed', str(caught.exception))
        self.assertEqual(self.calls, [])

    def test_bitlocker_warns_and_refuses_new_secure_boot_keys(self):
        record, emit = self.finalize(fstype='BitLocker')
        self.assertIn(finalize_worker.BITLOCKER_NOTE, record['warnings'])
        self.assertIn(finalize_worker.BITLOCKER_NOTE, [c.kwargs.get('text') for c in emit.call_args_list])
        self.calls, self.promoted = [], False
        with self.assertRaises(ValidationError):
            self.finalize(fstype='BitLocker', enroll=True)
        self.assertEqual(self.calls, [])

    def test_a_changed_partition_of_another_system_is_reported(self):
        original = self.table
        def moved():
            table = json.loads(original())
            if self.promoted:
                table['partitiontable']['partitions'][1]['size'] -= 2048
            return json.dumps(table)
        self.table = moved
        with self.assertRaises(ValidationError) as caught:
            self.finalize()
        self.assertIn('another system', str(caught.exception))

    def test_esp_helpers(self):
        runner = type('R', (), {'run': lambda _, args, **kw: self.run_command(args, **kw)})()
        self.assertEqual(finalize_worker.existing_esp(runner, {'path': '/dev/vda', 'pttype': 'gpt'}), self.ESP)
        self.assertIsNone(finalize_worker.existing_esp(runner, {'path': '/dev/vda', 'pttype': None}))
        point = self.tmp / 'esp'
        (point / 'EFI/Microsoft/Boot').mkdir(parents=True)
        (point / 'EFI/Microsoft/Boot/bootmgfw.efi').write_bytes(b'MZ')
        free, windows = finalize_worker.inspect_esp(runner, self.ESP, point)
        self.assertTrue(windows)
        self.assertGreater(free, 0)
        self.assertEqual(self.calls[-2][:3], ['mount', '-o', 'ro,nosuid,nodev,noexec'])
        self.assertEqual(self.calls[-1], ['umount', str(point)])

def completed(args, returncode=0, stdout='', stderr=''):
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


class PartitionTableTests(unittest.TestCase):
    """CMP-149: a device without a partition table is an answer, not a failed command."""

    def ask(self, result):
        with patch.object(storage_worker.subprocess, 'run', return_value=result) as run, \
                patch.object(storage_worker.LOG, 'warning') as warning:
            try:
                return storage_worker.partition_table('/dev/vda'), warning
            finally:
                self.assertEqual(run.call_args.args[0], ['sfdisk', '--json', '/dev/vda'])
                self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')

    def test_blank_device_is_none_without_a_warning(self):
        table, warning = self.ask(completed([], 1, stderr='sfdisk: /dev/vda: does not contain a recognized partition table\n'))
        self.assertIsNone(table)
        warning.assert_not_called()

    def test_real_failures_still_warn(self):
        with self.assertRaises(ValidationError):
            self.ask(completed([], 1, stderr='sfdisk: cannot open /dev/vda: Permission denied\n'))
        with patch.object(storage_worker.subprocess, 'run', return_value=completed([], 1, stderr='sfdisk: I/O error')), \
                patch.object(storage_worker.LOG, 'warning') as warning:
            self.assertTrue(storage_worker.gap_free('/dev/vda'))
            warning.assert_called_once()

    def test_table_is_parsed(self):
        table, warning = self.ask(completed([], 0, stdout=json.dumps({'partitiontable': {'label': 'gpt', 'partitions': []}})))
        self.assertEqual(table['label'], 'gpt')
        warning.assert_not_called()
        with self.assertRaises(ValidationError):
            self.ask(completed([], 0, stdout='not json'))

    def test_fresh_preview_partition_is_free_for_the_record_without_a_warning(self):
        answer = completed([], 1, stderr='sfdisk: /dev/sdc2: does not contain a recognized partition table\n')
        with patch.object(storage_worker.subprocess, 'run', return_value=answer), \
                patch.object(storage_worker.LOG, 'warning') as warning:
            self.assertTrue(storage_worker.gap_free('/dev/sdc2'))
        warning.assert_not_called()


class DirtyPreviewTests(unittest.TestCase):
    """CMP-146: a preview that was not shut down properly still finalizes, the preview
    itself is never written, and what cannot be opened gets a clear way out."""

    class Runner:
        def __init__(self, fail=()):
            self.calls, self.fail = [], fail

        def run(self, args, **kw):
            self.calls.append(args)
            if args[0] in self.fail:
                raise ValidationError(f'Ошибка {args[0]} (код 32)\nmount: /mnt/x: cannot mount /dev/nbd0p3 read-only.')
            if args[0] == 'qemu-img':
                Path(args[-1]).write_bytes(b'')
            if args[0] == 'sfdisk':
                return json.dumps({'partitiontable': {'label': 'gpt', 'partitions': [{'node': '/dev/nbd0p1', 'start': 2048}]}})
            if args[0] == 'blkid':
                return 'crypto_LUKS\n'
            return ''

    def attach(self, image, runner):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__('shutil').rmtree(tmp, ignore_errors=True))
        source = finalize_worker.Source(runner, image)
        with patch.object(finalize_worker, 'OVERLAY_DIR', str(tmp)), \
                patch.object(finalize_worker, 'free_nbd', return_value='/dev/nbd0'):
            source.attach()
        return source, tmp

    def test_both_image_kinds_are_read_through_a_throwaway_overlay(self):
        for image in ({'format': 'raw', 'path': '/dev/sdc2', 'on_target': False},
                      {'format': 'qcow2', 'path': str(PREVIEW / 'ram/preview.qcow2'), 'on_target': False}):
            runner = self.Runner()
            source, tmp = self.attach(image, runner)
            create = next(c for c in runner.calls if c[0] == 'qemu-img')
            overlay = create[-1]
            self.assertEqual(create[create.index('-b') + 1], image['path'])
            self.assertEqual(create[create.index('-F') + 1], image['format'])
            self.assertTrue(overlay.startswith(str(tmp) + '/'))
            connect = next(c for c in runner.calls if c[0] == 'qemu-nbd')
            # The preview itself is never handed to a writer: only the overlay is.
            self.assertEqual(connect[-2:], ['/dev/nbd0', overlay])
            self.assertNotIn(image['path'], connect)
            self.assertFalse(any(c[0] == 'losetup' for c in runner.calls))
            self.assertEqual(source.partition(3), '/dev/nbd0p3')
            with patch.object(finalize_worker.subprocess, 'run') as run, \
                    patch.object(finalize_worker, 'nbd_server', return_value=None):
                source.detach()
            self.assertEqual(run.call_args_list[0].args[0], ['qemu-nbd', '--disconnect', '/dev/nbd0'])
            self.assertFalse(Path(overlay).parent.exists())

    def test_encrypted_root_opens_writable_over_the_overlay(self):
        runner = self.Runner()
        source, _ = self.attach({'format': 'raw', 'path': '/dev/sdc2', 'on_target': False}, runner)
        device, encrypted = source.open_root(3, 'secret-pass')
        self.assertTrue(encrypted)
        self.assertEqual(device, '/dev/mapper/' + finalize_worker.SOURCE_MAP)
        opened = next(c for c in runner.calls if c[:2] == ['cryptsetup', 'open'])
        self.assertNotIn('--readonly', opened)
        self.assertEqual(opened[-2], '/dev/nbd0p3')
        with patch.object(finalize_worker.subprocess, 'run'), patch.object(finalize_worker, 'nbd_server', return_value=None):
            source.detach()

    def test_detach_waits_for_the_nbd_server_to_release_the_preview(self):
        runner = self.Runner()
        source, _ = self.attach({'format': 'raw', 'path': '/dev/sda2', 'on_target': True}, runner)
        alive = [True, True, False]
        with patch.object(finalize_worker.subprocess, 'run'), \
                patch.object(finalize_worker, 'nbd_server', return_value=4242), \
                patch.object(finalize_worker.Path, 'exists', side_effect=lambda *a: alive.pop(0) if alive else False), \
                patch.object(finalize_worker.time, 'sleep') as sleep:
            source.detach()
        self.assertEqual(sleep.call_count, 2)

    def test_a_root_that_still_does_not_mount_gets_a_clear_way_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValidationError) as caught:
                finalize_worker.read_record(self.Runner(fail=('mount',)), '/dev/nbd0p3', Path(tmp))
        self.assertEqual(str(caught.exception), finalize_worker.UNREADABLE)
        self.assertIn('shut it down from its power menu', str(caught.exception))
        self.assertIsNotNone(caught.exception.__cause__)  # the mount error stays in the log

    def swapfile(self, root, signature):
        path = root / finalize_worker.SWAPFILE
        path.parent.mkdir(parents=True)
        path.write_bytes(b'\0' * (finalize_worker.PAGE - 10) + signature + b'\0' * 4096)
        return path

    def test_hibernated_preview_is_not_resumed_after_promotion(self):
        for signature, discarded in ((b'S1SUSPEND\0', True), (b'LINHIB0001', True), (b'SWAPSPACE2', False)):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = self.swapfile(root, signature)
                runner = self.Runner()
                with patch.object(finalize_worker, 'emit'):
                    self.assertEqual(finalize_worker.discard_hibernation_image(runner, root), discarded)
                self.assertEqual(runner.calls, [['mkswap', str(path)]] if discarded else [])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(finalize_worker.discard_hibernation_image(self.Runner(), Path(tmp)))


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
                'image': {'format': 'raw', 'path': '/dev/sda2'}, 'layout': 'alongside', 'confirmation': '/dev/sda', 'enroll_keys': False}
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
