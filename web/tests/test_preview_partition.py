"""A new preview partition starts clean at both ends (found on the stand: a nested GPT backup
left by an earlier preview of the same size made the installer's sgdisk --zap-all fail)."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: F401 (sets the engine import path)
import storage_worker


class NewPartitionTests(unittest.TestCase):
    def test_both_ends_are_zeroed(self):
        calls, disks = [], iter([{'partitions': []}, {'partitions': [{'path': '/dev/vda1'}]}])

        def sh(args, **kw):
            calls.append(args)
            return '41938944\n' if args[0] == 'blockdev' else ''
        with patch.object(storage_worker, 'sh', side_effect=sh), \
                patch.object(storage_worker, 'inventory_disk', side_effect=lambda disk: next(disks)):
            self.assertEqual(storage_worker.new_partition('/dev/vda', 2048, 41940991), '/dev/vda1')
        wipes = [c for c in calls if c[0] == 'dd']
        self.assertEqual(wipes[0], ['dd', 'if=/dev/zero', 'of=/dev/vda1', 'bs=1M', 'count=1', 'conv=fsync'])
        self.assertEqual(wipes[1], ['dd', 'if=/dev/zero', 'of=/dev/vda1', 'bs=512', f'seek={41938944 - 2048}', 'count=2048',
                                    'conv=fsync'])


if __name__ == '__main__':
    unittest.main()
