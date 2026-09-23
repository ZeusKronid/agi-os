import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: F401 (sets the engine import path)
import deployment
import finalize_worker
import storage_worker
from controller import DemoProvider
from domain import Configuration, ValidationError
from system import demo_inventory

GIB = 2**30


def gpt(partitions, size):
    return json.dumps({'partitiontable': {'label': 'gpt', 'firstlba': 2048, 'lastlba': size // 512 - 34,
                                          'partitions': partitions}})


class ConsentTests(unittest.TestCase):
    def setUp(self):
        self.config = Configuration.parse(DemoProvider().reply('', [])['configuration'])
        self.snapshot = demo_inventory()
        self.snapshot.update(live=True, firmware='uefi')

    def test_disk_identity_change_invalidates_consent(self):
        before = deployment.consent(self.config, self.snapshot)
        self.snapshot['disks'][0]['fingerprint'] = 'replacement-disk'
        after = deployment.consent(self.config, self.snapshot)
        self.assertNotEqual(before['digest'], after['digest'])

    def test_busy_target_rejected(self):
        self.snapshot['disks'][0].update(eligible=False, reason='mounted')
        with self.assertRaises(ValidationError):
            deployment.consent(self.config, self.snapshot)

    def test_workers_refuse_host_even_as_root(self):
        for module, function in ((finalize_worker, finalize_worker.checked_request),):
            with patch.object(module.os, 'geteuid', return_value=0), patch.object(module, 'live_environment', return_value=False):
                with self.assertRaises(ValidationError):
                    function({})


class FreeSpaceTests(unittest.TestCase):
    def test_gaps_between_partitions_are_aligned_and_reported(self):
        size = 64 * GIB
        table = gpt([{'node': '/dev/sda1', 'start': 2048, 'size': 2 * GIB // 512},
                     {'node': '/dev/sda2', 'start': 10 * GIB // 512 + 5, 'size': 20 * GIB // 512}], size)
        disk = {'path': '/dev/sda', 'size': size, 'pttype': 'gpt', 'fstype': None}
        with patch.object(storage_worker, 'sh', return_value=table):
            regions = storage_worker.free_regions(disk)
        self.assertEqual(len(regions), 2)
        for start, end in regions:
            self.assertEqual(start % 2048, 0)
            self.assertEqual((end + 1) % 2048, 0)
        self.assertGreater(regions[1][1] - regions[1][0], 30 * GIB // 512)

    def test_blank_disk_is_free_but_bare_filesystem_is_user_data(self):
        blank = {'path': '/dev/sdb', 'size': 8 * GIB, 'pttype': None, 'fstype': None}
        with patch.object(storage_worker, 'looks_blank', return_value=True):
            self.assertEqual(storage_worker.free_regions(blank), [(2048, 8 * GIB // 512 - 34)])
        bare = {'path': '/dev/sdb', 'size': 8 * GIB, 'pttype': None, 'fstype': 'exfat'}
        self.assertEqual(storage_worker.free_regions(bare), [])

    def test_mbr_disk_offers_no_partition_space(self):
        disk = {'path': '/dev/sdc', 'size': 8 * GIB, 'pttype': 'dos', 'fstype': None}
        with patch.object(storage_worker, 'sh', return_value=json.dumps({'partitiontable': {'label': 'dos', 'partitions': []}})):
            self.assertEqual(storage_worker.free_regions(disk), [])


class ProbeTests(unittest.TestCase):
    def test_non_destructive_options_are_recommended_first(self):
        snapshot = demo_inventory()
        target = snapshot['disks'][0]
        target.update(pttype=None, fstype=None, partitions=[], tran='sata')
        with patch.object(storage_worker, 'inventory', return_value=snapshot), \
                patch.object(storage_worker, 'mem_available', return_value=4 * GIB), \
                patch.object(storage_worker, 'read_command', return_value='/dev/sr0\n'), \
                patch.object(storage_worker, 'looks_blank', return_value=True):
            result = storage_worker.probe({'needed': 6 * GIB, 'target': '/dev/vda', 'vm_memory': 4 * GIB})
        kinds = {o['kind']: o for o in result['options']}
        self.assertFalse(kinds['ram']['fits'])
        self.assertTrue(kinds['partition']['fits'])
        self.assertTrue(kinds['partition'].get('recommended'))
        self.assertFalse(kinds['erase'].get('recommended'))
        self.assertTrue(kinds['erase']['destructive'])
        self.assertEqual(kinds['erase']['confirm'], '/dev/vda')

    def test_ram_recommended_when_it_fits(self):
        snapshot = demo_inventory()
        snapshot['disks'][0].update(pttype=None, fstype=None, partitions=[])
        with patch.object(storage_worker, 'inventory', return_value=snapshot), \
                patch.object(storage_worker, 'mem_available', return_value=20 * GIB), \
                patch.object(storage_worker, 'read_command', return_value='/dev/sr0\n'), \
                patch.object(storage_worker, 'looks_blank', return_value=True):
            result = storage_worker.probe({'needed': 6 * GIB, 'target': '/dev/vda', 'vm_memory': 4 * GIB})
        ram = next(o for o in result['options'] if o['kind'] == 'ram')
        self.assertTrue(ram['fits'])
        self.assertTrue(ram.get('recommended'))

    def test_erase_is_never_reverted_silently(self):
        with patch.object(storage_worker, 'inventory', return_value=demo_inventory()):
            result = storage_worker.revert({'state': {'kind': 'erase', 'disk': '/dev/vda', 'device': '/dev/vda1'}})
        self.assertFalse(result['reverted'])


class PromoteTests(unittest.TestCase):
    def test_nested_partitions_keep_absolute_sectors(self):
        calls = []
        base = 4 * GIB // 512
        outer = gpt([{'node': '/dev/vda1', 'start': 2048, 'size': base - 2048, 'name': 'DATA'},
                     {'node': '/dev/vda2', 'start': base, 'size': 16 * GIB // 512, 'name': 'AGIOS-PREVIEW'}], 64 * GIB)
        nested = [{'node': '/dev/loop0p1', 'start': 2048, 'size': GIB // 512, 'name': 'AGI-BOOT'},
                  {'node': '/dev/loop0p2', 'start': 2048 + GIB // 512, 'size': 14 * GIB // 512, 'name': 'AGI-ROOT'}]
        refreshed = gpt([{'node': '/dev/vda1', 'start': 2048, 'size': base - 2048},
                         {'node': '/dev/vda2', 'start': base + 2048, 'size': GIB // 512},
                         {'node': '/dev/vda3', 'start': base + 2048 + GIB // 512, 'size': 14 * GIB // 512}], 64 * GIB)
        class Runner:
            def run(self, args, **kw):
                calls.append(args)
                if args[0] == 'sfdisk':
                    return outer if len([c for c in calls if c[0] == 'sfdisk']) == 1 else refreshed
                return ''
        class Source:
            partitions = nested
        request = {'image': {'format': 'raw', 'path': '/dev/vda2'}, 'layout': 'alongside'}
        with patch.object(finalize_worker, 'emit'):
            boot, root, _ = finalize_worker.promote(Runner(), request, {'path': '/dev/vda'}, Source(), 'uefi')
        self.assertEqual((boot, root), ('/dev/vda2', '/dev/vda3'))
        sgdisk = [c for c in calls if c[0] == 'sgdisk' and any(a.startswith('--new') for a in c)][0]
        self.assertIn(f'--new=0:{base + 2048}:{base + 2048 + GIB // 512 - 1}', sgdisk)
        self.assertIn('--delete=2', sgdisk)
        self.assertNotIn('--delete=1', sgdisk)  # alongside keeps the user's partition
        zeroing = [c for c in calls if c[0] == 'dd']
        self.assertEqual(len(zeroing), 2)
        # The nested table and the preview record before the first nested partition are erased.
        self.assertIn(f'seek={base}', zeroing[0])
        self.assertIn('count=2048', zeroing[0])


class HibernationTests(unittest.TestCase):
    def test_reserved_swap_file_costs_no_memory_but_needs_disk(self):
        snapshot = demo_inventory()
        snapshot['disks'][0].update(pttype=None, fstype=None, partitions=[], size=20 * GIB)
        with patch.object(storage_worker, 'inventory', return_value=snapshot), \
                patch.object(storage_worker, 'mem_available', return_value=14 * GIB), \
                patch.object(storage_worker, 'read_command', return_value='/dev/sr0\n'):
            result = storage_worker.probe({'needed': 22 * GIB, 'sparse': 16 * GIB, 'target': '/dev/vda', 'vm_memory': 4 * GIB})
            with self.assertRaises(ValidationError):
                storage_worker.probe({'needed': 6 * GIB, 'sparse': 7 * GIB, 'target': '/dev/vda', 'vm_memory': 4 * GIB})
        kinds = {o['kind']: o for o in result['options']}
        self.assertTrue(kinds['ram']['fits'])  # 6 GiB of real data, the swap file is only reserved
        # 20 GiB of disk cannot hold 22 GiB (a disk without GPT is offered only for erase since CMP-135).
        self.assertFalse(any(o['fits'] for o in result['options'] if o['kind'] != 'ram'))
        self.assertIn('erase', kinds)

    def test_copy_skips_swap_and_reserves_room_for_it(self):
        calls = []
        table = gpt([], 64 * GIB)
        refreshed = gpt([{'node': '/dev/vda1', 'start': 2048, 'size': GIB // 512},
                         {'node': '/dev/vda2', 'start': 2048 + GIB // 512, 'size': 40 * GIB // 512}], 64 * GIB)

        class Runner:
            def run(self, args, **kw):
                calls.append(args)
                if args[0] == 'du':
                    return f'{4 * GIB}\t/x\n'
                if args[0] == 'sfdisk':
                    return table if len([c for c in calls if c[0] == 'sfdisk']) == 1 else refreshed
                if args[0] == 'blkid':
                    return 'ext4\n'
                return ''

        class Source:
            mount = None
            def open_root(self, number, passphrase):
                return '/dev/nbd0p2', False
            def partition(self, number):
                return f'/dev/nbd0p{number}'

        import tempfile
        with tempfile.TemporaryDirectory() as tmp, patch.object(finalize_worker, 'emit'):
            finalize_worker.copy(Runner(), {'layout': 'erase'}, {'path': '/dev/vda', 'size': 64 * GIB}, Source(), 'uefi', '',
                                 Path(tmp), ['swap'], 16 * GIB)
            du = [c for c in calls if c[0] == 'du'][0]
            self.assertIn(f'--exclude={Path(tmp) / "source/swap"}', du)
        rsyncs = [c for c in calls if c[0] == 'rsync' and '-rt' not in c and '-rcn' not in c]
        self.assertEqual(len(rsyncs), 2)
        for command in rsyncs:
            self.assertIn('--exclude=/swap', command)

    def test_recreated_swap_file_follows_the_new_filesystem(self):
        record = {'hibernation': {'file': '/swap/swapfile', 'size': 8 * GIB, 'resume_uuid': 'old', 'resume_offset': 1}}
        created = []

        class Runner:
            def run(self, args, **kw):
                return 'btrfs\n' if args[0] == 'findmnt' else ''

        with patch.object(finalize_worker, 'inventory', return_value={'hardware': {'memory': int(15.5 * GIB)}}):
            size = finalize_worker.swapfile_size(record)
        self.assertEqual(size, 16 * GIB)
        with patch.object(finalize_worker, 'inventory', return_value={'hardware': {'memory': 0}}):
            self.assertEqual(finalize_worker.swapfile_size(record), 8 * GIB)
        with patch.object(finalize_worker, 'emit'), patch.object(finalize_worker, 'create_swapfile',
                                                                side_effect=lambda r, d, fs, s: created.append((fs, s)) or 777):
            resume = finalize_worker.recreate_swapfile(Runner(), Path('/mnt/x'), 'new-uuid', record, size)
        self.assertEqual(resume, 'resume=UUID=new-uuid resume_offset=777')
        self.assertEqual(created, [('btrfs', 16 * GIB)])
        self.assertEqual(record['hibernation']['resume_uuid'], 'new-uuid')
        self.assertEqual(record['hibernation']['size'], 16 * GIB)


if __name__ == '__main__':
    unittest.main()
