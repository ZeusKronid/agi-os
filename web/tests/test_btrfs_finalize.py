"""Finishing a btrfs preview with subvolumes (CMP-153): each subvolume is copied into the
same subvolume of the new root, snapshots stay behind, and the boot entry names @."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: F401 (sets the engine import path)
import finalize_worker

GIB = 2**30


def gpt(partitions, size):
    return json.dumps({'partitiontable': {'label': 'gpt', 'firstlba': 2048, 'lastlba': size // 512 - 34,
                                          'partitions': partitions}})


class BtrfsCopyTests(unittest.TestCase):
    def test_copy_keeps_the_subvolumes(self):
        calls = []
        table = gpt([], 64 * GIB)
        refreshed = gpt([{'node': '/dev/vda1', 'start': 2048, 'size': GIB // 512},
                         {'node': '/dev/vda2', 'start': 2048 + GIB // 512, 'size': 40 * GIB // 512}], 64 * GIB)

        class Runner:
            def run(self, args, **kw):
                calls.append(args)
                if args[0] == 'mount' and 'subvolid=5' in ''.join(args):
                    for name in ('@', '@home', '@log', '@pkg', '@snapshots'):
                        (Path(args[-1]) / name).mkdir()
                if args[0] == 'umount' and Path(args[-1]).name.startswith('agi-subvolumes-'):
                    for child in Path(args[-1]).iterdir():
                        child.rmdir()
                if args[0] == 'du':
                    return f'{4 * GIB}\t/x\n'
                if args[0] == 'sfdisk':
                    return table if len([c for c in calls if c[0] == 'sfdisk']) == 1 else refreshed
                if args[0] == 'blkid':
                    return 'btrfs\n'
                return ''

        class Source:
            mount = None
            def open_root(self, number, passphrase):
                return '/dev/nbd0p2', False
            def partition(self, number):
                return f'/dev/nbd0p{number}'

        plan = finalize_worker.layout.plan_for(SimpleNamespace(filesystem='btrfs', swap='zram'), 'uefi')
        with tempfile.TemporaryDirectory() as tmp, patch.object(finalize_worker, 'emit'):
            finalize_worker.copy(Runner(), {'layout': 'erase'}, {'path': '/dev/vda', 'size': 64 * GIB}, Source(), plan, '',
                                 Path(tmp), [], 0)
            source = Path(tmp) / 'source'
            target = Path(tmp) / 'target'
            # The preview's subvolumes are mounted read-only in place, the new ones read-write.
            self.assertIn(['mount', '-o', 'subvol=@home,' + finalize_worker.SOURCE_MOUNT, '/dev/nbd0p2', f'{source}/home'], calls)
            self.assertIn(['mount', '-o', 'subvol=@home', '/dev/vda2', f'{target}/home'], calls)
            created = [c[-1].rsplit('/', 1)[1] for c in calls if c[:3] == ['btrfs', 'subvolume', 'create']]
            self.assertEqual(created, ['@', '@home', '@log', '@pkg', '@snapshots'])
            du = [c for c in calls if c[0] == 'du'][0]
            self.assertNotIn('-sxB1', du)  # subvolumes are other file systems to du -x
            self.assertIn(f'--exclude={source / ".snapshots"}', du)
            copy = [c for c in calls if c[0] == 'rsync' and '-aHAX' in c][0]
            self.assertIn('--exclude=/.snapshots/*', copy)
            self.assertIn(['umount', '--recursive', str(source)], calls)


if __name__ == '__main__':
    unittest.main()
