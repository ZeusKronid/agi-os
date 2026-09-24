"""A Live booted into memory (copytoram) still answers on localhost with a way out,
instead of a website that exits and leaves the browser on an unreachable page."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import system
from aiohttp.test_utils import AioHTTPTestCase


class RamBootPageTests(AioHTTPTestCase):
    async def get_application(self):
        return server.ram_boot_application(port=8787)

    async def test_page_explains_how_to_boot_again(self):
        response = await self.client.get('/', headers={'Host': 'localhost:8787'})
        self.assertEqual(response.status, 200)
        self.assertIn('AGI OS live', await response.text())

    async def test_state_answers_so_the_browser_opens_the_page(self):
        # agi-installer opens Firefox once GET /api/state succeeds.
        response = await self.client.get('/api/state', headers={'Host': 'localhost:8787'})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())['phase'], 'unsupported')

    async def test_other_hosts_are_rejected(self):
        response = await self.client.get('/', headers={'Host': 'example.com'})
        self.assertEqual(response.status, 403)


class CopiedToRamTests(unittest.TestCase):
    def test_detects_a_boot_into_memory_only_without_the_boot_medium(self):
        with patch.object(system.Path, 'is_dir', return_value=True):
            with patch.object(system, 'live_environment', return_value=False):
                self.assertTrue(system.copied_to_ram())
            with patch.object(system, 'live_environment', return_value=True):
                self.assertFalse(system.copied_to_ram())
        with patch.object(system.Path, 'is_dir', return_value=False), \
                patch.object(system, 'live_environment', return_value=False):
            self.assertFalse(system.copied_to_ram())
