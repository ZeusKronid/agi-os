import json
from pathlib import Path
import sys
from types import SimpleNamespace
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
        with patch.object(storage_worker, 'partition_table', return_value=json.loads(table)['partitiontable']):
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
        with patch.object(storage_worker, 'partition_table', return_value={'label': 'dos', 'partitions': []}):
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
            boot, root, _ = finalize_worker.promote(Runner(), request, {'path': '/dev/vda'}, Source(),
                                                     finalize_worker.layout.plan_for(SimpleNamespace(filesystem='ext4'), 'uefi'))
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


def dos(partitions):
    return json.dumps({'partitiontable': {'label': 'dos', 'partitions': partitions}})


def mbr_plan():
    return finalize_worker.layout.plan_for(SimpleNamespace(filesystem='ext4', partition_table='msdos', bootloader='grub'), 'bios')


class MbrFinalizeTests(unittest.TestCase):
    """CMP-152: an msdos preview becomes the disk's MBR."""

    def test_promote_writes_an_mbr_over_the_same_sectors_without_wiping_them(self):
        calls, inputs = [], []
        base = 2048
        outer = gpt([{'node': '/dev/vda1', 'start': base, 'size': 20 * GIB // 512, 'name': 'AGIOS-PREVIEW'}], 64 * GIB)
        nested = [{'node': '/dev/loop0p1', 'start': 2048, 'size': GIB // 512},
                  {'node': '/dev/loop0p2', 'start': 2048 + GIB // 512, 'size': 18 * GIB // 512}]
        boot_start, root_start = base + 2048, base + 2048 + GIB // 512
        refreshed = dos([{'node': '/dev/vda1', 'start': boot_start, 'size': GIB // 512},
                         {'node': '/dev/vda2', 'start': root_start, 'size': 18 * GIB // 512}])
        class Runner:
            def run(self, args, input_text=None, **kw):
                calls.append(args); inputs.append(input_text)
                if args[:2] == ['sfdisk', '--json']:
                    return outer if len([c for c in calls if c[:2] == ['sfdisk', '--json']]) == 1 else refreshed
                return ''
        class Source:
            partitions, device, label = nested, '/dev/loop0', 'dos'
        request = {'image': {'format': 'raw', 'path': '/dev/vda1'}, 'layout': 'erase'}
        with patch.object(finalize_worker, 'emit'):
            boot, root, _ = finalize_worker.promote(Runner(), request, {'path': '/dev/vda'}, Source(), mbr_plan())
        self.assertEqual((boot, root), ('/dev/vda1', '/dev/vda2'))
        write = calls.index(['sfdisk', '--wipe', 'always', '--wipe-partitions', 'never', '--label', 'dos', '/dev/vda'])
        self.assertEqual(inputs[write], f'start={boot_start}, size={GIB // 512}, type=83, bootable\n'
                                        f'start={root_start}, size={18 * GIB // 512}, type=83\n')
        self.assertLess(calls.index(['sgdisk', '--zap-all', '/dev/vda']), write)
        zeroing = [c for c in calls if c[0] == 'dd']
        self.assertEqual(len(zeroing), 1)  # No GPT backup at the end of an MBR preview: its root runs there.
        self.assertIn(f'seek={base}', zeroing[0])

    def test_promote_refuses_alongside_and_beyond_2_tib(self):
        nested = [{'node': '/dev/loop0p1', 'start': 2048, 'size': GIB // 512},
                  {'node': '/dev/loop0p2', 'start': 2048 + GIB // 512, 'size': 18 * GIB // 512}]
        class Source:
            partitions, device, label = nested, '/dev/loop0', 'dos'
        for layout_name, base in (('alongside', 2048), ('erase', 2**32 - 4096)):
            calls = []
            outer = gpt([{'node': '/dev/vda1', 'start': base, 'size': 20 * GIB // 512, 'name': 'AGIOS-PREVIEW'}], 4096 * GIB)
            class Runner:
                def run(self, args, input_text=None, **kw):
                    calls.append(args)
                    return outer if args[:2] == ['sfdisk', '--json'] else ''
            with self.subTest(layout=layout_name), patch.object(finalize_worker, 'emit'), self.assertRaises(ValidationError):
                finalize_worker.promote(Runner(), {'image': {'path': '/dev/vda1'}, 'layout': layout_name},
                                        {'path': '/dev/vda'}, Source(), mbr_plan())
            self.assertEqual([c for c in calls if c[0] != 'sfdisk'], [])  # Refused before any write.

    def test_copy_creates_an_mbr_with_an_active_boot_partition(self):
        calls, inputs = [], []
        empty = dos([])
        refreshed = dos([{'node': '/dev/sda1', 'start': 2048, 'size': GIB // 512},
                         {'node': '/dev/sda2', 'start': 2048 + GIB // 512, 'size': 40 * GIB // 512}])
        class Runner:
            def run(self, args, input_text=None, **kw):
                calls.append(args); inputs.append(input_text)
                if args[0] == 'du':
                    return f'{4 * GIB}\t/x\n'
                if args[:2] == ['sfdisk', '--json']:
                    return empty if len([c for c in calls if c[:2] == ['sfdisk', '--json']]) == 1 else refreshed
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
            boot, root_partition, *_ = finalize_worker.copy(Runner(), {'layout': 'erase'}, {'path': '/dev/sda', 'size': 64 * GIB},
                                                            Source(), mbr_plan(), '', Path(tmp))
        self.assertEqual((boot, root_partition), ('/dev/sda1', '/dev/sda2'))
        label = calls.index(['sfdisk', '--wipe', 'always', '/dev/sda'])
        self.assertEqual(inputs[label], 'label: dos\n')
        append = calls.index(['sfdisk', '--append', '--wipe-partitions', 'never', '/dev/sda'])
        last = 64 * GIB // 512 - 1
        self.assertEqual(inputs[append], f'start=2048, size={GIB // 512}, type=83, bootable\n'
                                         f'start={2048 + GIB // 512}, size={last - (2048 + GIB // 512) + 1}, type=83\n')
        self.assertIn(['mkfs.ext4', '-F', '/dev/sda1'], calls)

    def test_copy_next_to_windows_on_mbr_appends_two_inactive_primaries(self):
        windows = [{'node': '/dev/sda1', 'start': 2048, 'size': 100 * 2048, 'type': '7', 'bootable': True},
                   {'node': '/dev/sda2', 'start': 206848, 'size': 30 * GIB // 512, 'type': '7'}]
        free = 206848 + 30 * GIB // 512
        mine = [{'node': '/dev/sda3', 'start': free, 'size': GIB // 512, 'type': '83'},
                {'node': '/dev/sda4', 'start': free + GIB // 512, 'size': 20 * GIB // 512, 'type': '83'}]
        for existing, fits in ((windows, True), (windows + [{'node': '/dev/sda3', 'start': free, 'size': 2048, 'type': '83'}], False)):
            calls, inputs = [], []
            class Runner:
                def run(self, args, input_text=None, **kw):
                    calls.append(args); inputs.append(input_text)
                    if args[0] == 'du':
                        return f'{4 * GIB}\t/x\n'
                    if args[:2] == ['sfdisk', '--json']:
                        return dos(existing + mine) if any(c[:2] == ['sfdisk', '--append'] for c in calls) else dos(existing)
                    if args[:2] == ['sfdisk', '--dump']:
                        return 'label: dos\n'
                    return 'ext4\n' if args[0] == 'blkid' else ''
            class Source:
                mount = None
                def open_root(self, number, passphrase):
                    return '/dev/nbd0p2', False
                def partition(self, number):
                    return f'/dev/nbd0p{number}'
            import tempfile
            with self.subTest(fits=fits), tempfile.TemporaryDirectory() as tmp, patch.object(finalize_worker, 'emit'), \
                    patch.object(finalize_worker, 'BACKUPS', Path(tmp)):
                (Path(tmp) / 'm').mkdir()
                disk = {'path': '/dev/sda', 'size': 64 * GIB, 'pttype': 'dos'}
                if not fits:
                    with self.assertRaises(ValidationError):
                        finalize_worker.copy(Runner(), {'layout': 'alongside'}, disk, Source(), mbr_plan(), '', Path(tmp) / 'm')
                    self.assertFalse([c for c in calls if c[0] in ('sfdisk', 'sgdisk', 'mkfs.ext4') and c[1] != '--json'])
                    continue
                boot, root_partition, *_ = finalize_worker.copy(Runner(), {'layout': 'alongside'}, disk, Source(),
                                                                mbr_plan(), '', Path(tmp) / 'm')
                self.assertEqual((boot, root_partition), ('/dev/sda3', '/dev/sda4'))
                self.assertTrue((Path(tmp) / 'agi-final-sda.sfdisk').is_file())
                append = calls.index(['sfdisk', '--append', '--wipe-partitions', 'never', '/dev/sda'])
                self.assertNotIn('bootable', inputs[append])  # Windows' partition stays the active one.
                self.assertTrue(inputs[append].startswith(f'start={free}, size={GIB // 512}, type=83\n'))
                self.assertFalse([c for c in calls if c[0] == 'sgdisk' or c[:3] == ['sfdisk', '--wipe', 'always']])

    def test_bios_windows_is_found_by_its_boot_manager_and_chainloaded(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp)
            def mount(device, fstype, point):
                point.mkdir(parents=True, exist_ok=True)
                if device == '/dev/sda1':
                    (point / 'bootmgr').write_text('')
                return device != '/dev/sda3'
            disk = {'pttype': 'dos', 'partitions': [
                {'path': '/dev/sda3', 'fstype': 'ntfs', 'mounted': False},
                {'path': '/dev/sda1', 'fstype': 'ntfs', 'mounted': False},
                {'path': '/dev/sda2', 'fstype': 'ntfs', 'mounted': False}]}
            with patch.object(finalize_worker.storage_worker, 'PREVIEW', preview), \
                    patch.object(finalize_worker.storage_worker, 'read_only_mount', side_effect=mount), \
                    patch.object(finalize_worker.subprocess, 'run'):
                self.assertEqual(finalize_worker.bios_windows(disk)['path'], '/dev/sda1')
                self.assertIsNone(finalize_worker.bios_windows({**disk, 'pttype': 'gpt'}))
        entry = finalize_worker.bios_windows_entry('1234-ABCD')
        self.assertIn('search --no-floppy --fs-uuid --set=root 1234-ABCD', entry)
        self.assertIn('chainloader +1', entry)
        self.assertIn('insmod part_msdos', entry)

    def test_alongside_keeps_the_table_type(self):
        for pttype, table in (('dos', 'gpt'), ('gpt', 'msdos')):
            plan = mbr_plan() if table == 'msdos' else finalize_worker.layout.plan_for(SimpleNamespace(filesystem='ext4'), 'bios')
            with self.subTest(pttype=pttype), self.assertRaises(ValidationError):
                finalize_worker.check_table(plan, {'pttype': pttype, 'size': 64 * GIB}, 'alongside')
            finalize_worker.check_table(plan, {'pttype': pttype, 'size': 64 * GIB}, 'erase')
        # copy() itself refuses a GPT plan next to an MBR disk before touching anything (sgdisk would convert it).
        calls = []
        class Runner:
            def run(self, args, input_text=None, **kw):
                calls.append(args)
                return ''
        gpt_plan = finalize_worker.layout.plan_for(SimpleNamespace(filesystem='ext4'), 'bios')
        with self.assertRaises(ValidationError):
            finalize_worker.copy(Runner(), {'layout': 'alongside'}, {'path': '/dev/sda', 'size': 64 * GIB, 'pttype': 'dos'},
                                 None, gpt_plan, '', Path('/nonexistent-agios-test'))
        self.assertEqual(calls, [])
        finalize_worker.check_table(mbr_plan(), {'pttype': 'dos', 'size': 64 * GIB}, 'alongside')
        finalize_worker.check_table(mbr_plan(), {'pttype': None, 'size': 64 * GIB}, 'alongside')
        with self.assertRaises(ValidationError):
            finalize_worker.check_table(mbr_plan(), {'pttype': None, 'size': 4096 * GIB}, 'erase')


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
            finalize_worker.copy(Runner(), {'layout': 'erase'}, {'path': '/dev/vda', 'size': 64 * GIB}, Source(),
                                 finalize_worker.layout.plan_for(SimpleNamespace(filesystem='ext4'), 'uefi'), '',
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



class CopyTableTests(unittest.TestCase):
    """The partition table the copy finalization starts from."""

    def calls(self, layout, disk, blank=True):
        calls = []
        class Runner:
            def run(self, args, **kw):
                calls.append(args)
                return ''
        with patch.object(finalize_worker.storage_worker, 'looks_blank', return_value=blank):
            finalize_worker.prepare_table(Runner(), layout, disk)
        return calls

    def test_alongside_on_a_new_empty_disk_creates_a_table(self):
        calls = self.calls('alongside', {'path': '/dev/vda', 'pttype': None, 'fstype': None})
        self.assertEqual(calls[0], ['sgdisk', '--clear', '/dev/vda'])
        self.assertTrue(calls[1][1].startswith('--backup='))

    def test_alongside_keeps_an_existing_table(self):
        calls = self.calls('alongside', {'path': '/dev/vda', 'pttype': 'gpt', 'fstype': None})
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][1].startswith('--backup='))

    def test_alongside_refuses_data_without_a_table(self):
        for disk, blank in (({'path': '/dev/vda', 'pttype': None, 'fstype': 'ntfs'}, True),
                            ({'path': '/dev/vda', 'pttype': None, 'fstype': None}, False)):
            with self.assertRaises(ValidationError):
                self.calls('alongside', disk, blank)

    def test_erase_always_starts_from_an_empty_table(self):
        calls = self.calls('erase', {'path': '/dev/vda', 'pttype': 'gpt', 'fstype': None})
        self.assertEqual([c[1] for c in calls], ['--zap-all', '--clear'])

if __name__ == '__main__':
    unittest.main()
