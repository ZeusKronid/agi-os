import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'archiso/airootfs/usr/local/share/agi-os/installer'))
from system import Catalog
from domain import ValidationError

class CatalogTests(unittest.TestCase):
    def test_fresh_live_boot_syncs_before_lookup(self):
        with patch('system.live_environment',return_value=True), patch('system.Path.is_file',return_value=False), patch('system.read_command',side_effect=['synced','core python 3.14\nextra foo 1.0\n']) as read:
            catalog=Catalog()
            self.assertEqual(catalog.validate(['python']),['core/python'])
            self.assertEqual(read.call_args_list[0].args[0],['sudo','-n','/usr/bin/pacman','-Sy','--noconfirm'])
            catalog.search(['foo'])
            self.assertEqual(read.call_count,2)
    def test_empty_catalog_is_not_cached_and_host_never_syncs(self):
        with patch('system.live_environment',return_value=False), patch('system.read_command',side_effect=['','core python 3.14\n']) as read:
            catalog=Catalog()
            with self.assertRaises(ValidationError):catalog.load()
            self.assertIsNone(catalog.entries)
            self.assertIn('python',catalog.load())
            self.assertTrue(all(c.args[0][0]=='pacman' for c in read.call_args_list))
    def test_sync_failure_does_not_cache_empty_results(self):
        with patch('system.live_environment',return_value=True), patch('system.Path.is_file',return_value=False), patch('system.read_command',side_effect=ValidationError('offline')):
            catalog=Catalog()
            with self.assertRaises(ValidationError):catalog.load()
            self.assertIsNone(catalog.entries)
