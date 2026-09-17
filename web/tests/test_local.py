import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from aiohttp.test_utils import AioHTTPTestCase
from controller import DemoProvider
from domain import Configuration
from guacamole import instruction, read_instruction, handshake


class LocalApiTests(AioHTTPTestCase):
    async def get_application(self):
        self.directory = tempfile.TemporaryDirectory()
        (Path(self.directory.name) / 'web/static').mkdir(parents=True)
        self.root_patch = patch.object(server, 'ROOT', Path(self.directory.name))
        self.provider_patch = patch.object(server, 'LiveProvider', DemoProvider)
        self.data_patch = patch.object(server, 'DATA_ROOT', Path(self.directory.name))
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.root_patch.start()
        self.provider_patch.start()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.provider_patch.stop)
        return server.application()

    async def request(self, path, body, headers=None):
        return await self.client.post(path, json=body, headers={
            'Host': 'localhost:8787', 'X-AGIOS': 'local', **(headers or {})})

    async def test_final_install_requires_built_current_configuration(self):
        state = self.app['state']
        state.controller.configuration = Configuration.parse(DemoProvider().reply('', [])['configuration'])
        response = await self.request('/api/final/install', {'digest': 'anything', 'confirmation': '/dev/vda', 'preview_accepted': True})
        self.assertEqual(response.status, 400)
        self.assertIsNone(state.deploy_task)

    async def test_final_install_rejects_running_preview(self):
        from types import SimpleNamespace
        state = self.app['state']
        config = Configuration.parse(DemoProvider().reply('', [])['configuration'])
        state.controller.configuration = config
        state.disk_ready, state.built_digest = True, config.digest()
        state.vm = SimpleNamespace(running=True)
        try:
            response = await self.request('/api/final/review', {'target':'/dev/vda'})
            self.assertEqual(response.status, 400)
            self.assertIsNone(state.final_review)
        finally:
            state.vm = None

    async def test_transfer_blocks_resume_and_second_submission(self):
        state = self.app['state']
        state.deployment['phase'] = 'writing'
        for path in ('/api/resume', '/api/stop', '/api/final/install'):
            response = await self.request(path, {})
            self.assertIn(response.status, (400, 409))
        self.assertIsNone(state.deploy_task)

    async def test_screenshot_api_is_not_part_of_product(self):
        response = await self.request('/api/screenshot', {})
        self.assertEqual(response.status, 404)

    async def test_runtime_refuses_to_start_outside_live(self):
        import runtime
        with patch.object(runtime, 'DATA_ROOT', Path(self.directory.name)), \
                patch.object(runtime, 'live_environment', return_value=False):
            vm = runtime.VirtualMachine()
            with self.assertRaisesRegex(RuntimeError, 'Live'):
                await vm.start()
            self.assertFalse((vm.directory / 'system.qcow2').exists())

    async def test_foreign_origin_cannot_start_vm(self):
        response = await self.request('/api/build', {}, {'Origin': 'https://example.org'})
        self.assertEqual(response.status, 403)
        self.assertIsNone(self.app['state'].vm)

    async def test_foreign_host_rejected(self):
        response = await self.client.get('/api/state', headers={'Host': 'evil.example'})
        self.assertEqual(response.status, 403)

    async def test_stale_confirmation_cannot_start_vm(self):
        state = self.app['state']
        state.controller.configuration = Configuration.parse(DemoProvider().reply('', [])['configuration'])
        response = await self.request('/api/build', {'digest': 'stale', 'password': 'public-test-fixture'})
        self.assertEqual(response.status, 400)
        self.assertIsNone(state.vm)

    async def test_password_never_in_state_or_session(self):
        state = self.app['state']
        config = Configuration.parse(DemoProvider().reply('', [])['configuration'])
        state.controller.configuration = config
        response = await self.request('/api/build', {'digest': config.digest(), 'password': 'short'})
        self.assertEqual(response.status, 400)
        state.persist()
        self.assertNotIn('password', state.record.read_text())
        self.assertNotIn('password', json.dumps(state.public()))

    async def test_saved_vm_survives_chat_persistence_without_running_vm(self):
        state = self.app['state']
        state.saved_vm = str(Path(self.directory.name) / 'vm/web-example')
        state.disk_ready = True
        state.persist()
        data = json.loads(state.record.read_text())
        self.assertEqual(data['vm'], state.saved_vm)
        self.assertTrue(data['disk_ready'])

    async def test_resume_rejects_path_outside_vm_directory(self):
        state = self.app['state']
        state.disk_ready, state.saved_vm = True, '/etc'
        response = await self.request('/api/resume', {})
        self.assertEqual(response.status, 400)
        self.assertIsNone(state.vm)

    async def test_successful_build_enables_resume(self):
        state = self.app['state']
        config = Configuration.parse(DemoProvider().reply('', [])['configuration'])
        state.controller.installing = True
        class VM:
            def __init__(self, *args):
                self.directory = Path(self_root) / 'vm/web-test'
                self.running = False
            async def start(self): self.running = True
            async def install(self, config, password, notify):
                notify({'kind': 'progress', 'text': 'Installing'})
                notify({'kind': 'installed', 'text': 'Installed'})
            async def stop(self): self.running = False
        self_root = self.directory.name
        with patch.object(server, 'VirtualMachine', VM):
            await state.build(config, 'public-test-fixture', 4096, 4)
        self.assertEqual(state.phase, 'ready')
        self.assertTrue(state.disk_ready)
        self.assertFalse(state.controller.installing)
        self.assertNotIn('public-test-fixture', state.record.read_text())

    async def test_failed_installation_is_not_resumable(self):
        state = self.app['state']
        config = Configuration.parse(DemoProvider().reply('', [])['configuration'])
        class VM:
            def __init__(self, *args):
                self.directory = Path(self_root) / 'vm/web-test'
                self.running = False
            async def start(self): raise RuntimeError('QEMU failed')
            async def stop(self): pass
        self_root = self.directory.name
        with patch.object(server, 'VirtualMachine', VM):
            await state.build(config, 'public-test-fixture', 4096, 4)
        self.assertEqual(state.phase, 'error')
        self.assertFalse(state.disk_ready)
        self.assertFalse(state.public()['can_resume'])


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_utf8_lengths_and_delimiters(self):
        reader = asyncio.StreamReader()
        reader.feed_data(instruction('test', 'русский,текст;').encode())
        reader.feed_eof()
        self.assertEqual(await read_instruction(reader), ['test', 'русский,текст;'])

    async def test_handshake_connects_only_assigned_local_console(self):
        reader = asyncio.StreamReader()
        reader.feed_data((instruction('args', 'VERSION_1_5_0', 'hostname', 'port', 'password') + instruction('ready', '$test')).encode())
        class Writer:
            def __init__(self): self.data = b''
            def write(self, data): self.data += data
            async def drain(self): pass
        writer = Writer()
        await handshake(reader, writer, 5905)
        self.assertIn(instruction('connect', 'VERSION_1_5_0', '127.0.0.1', '5905', '').encode(), writer.data)


if __name__ == '__main__':
    unittest.main()
