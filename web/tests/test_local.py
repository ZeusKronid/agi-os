import asyncio
import json
from types import SimpleNamespace
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
from system import demo_inventory
from guacamole import instruction, read_instruction, handshake


def live_demo_inventory():
    snapshot = demo_inventory()
    snapshot['live'] = True
    snapshot['disks'][0]['partitions'] = []
    return snapshot


def demo_configuration():
    return Configuration.parse(DemoProvider().reply('', [])['configuration'])


class LocalApiTests(AioHTTPTestCase):
    async def get_application(self):
        self.directory = tempfile.TemporaryDirectory()
        (Path(self.directory.name) / 'web/static').mkdir(parents=True)
        for target, value in (('ROOT', Path(self.directory.name)), ('LiveProvider', DemoProvider),
                              ('DATA_ROOT', Path(self.directory.name)), ('target_inventory', live_demo_inventory)):
            patcher = patch.object(server, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.directory.cleanup)
        return server.application()

    async def request(self, path, body, headers=None):
        return await self.client.post(path, json=body, headers={
            'Host': 'localhost:8787', 'X-AGIOS': 'local', **(headers or {})})

    def fake_plan(self, state, option=None):
        option = option or {'id': 'ram', 'kind': 'ram', 'title': 'RAM', 'detail': '', 'revert': 'nothing', 'destructive': False,
                            'confirm': None, 'fits': True, 'available': 10 * 2**30}
        state.plan = {'digest': 'plan-digest', 'estimate': {'installed': 1, 'download': 1, 'packages': 1}, 'needed': 2**30,
                      'memory': 4096, 'encrypt': True, 'compression': 1.0, 'options': [option], 'consent': state.current_consent()['digest']}
        return option

    async def test_build_requires_plan_and_matching_digest(self):
        state = self.app['state']
        state.controller.configuration = demo_configuration()
        response = await self.request('/api/build', {'digest': 'x', 'option': 'ram', 'accepted': True, 'password': 'public-test-fixture'})
        self.assertEqual(response.status, 400)
        self.fake_plan(state)
        response = await self.request('/api/build', {'digest': 'stale', 'option': 'ram', 'accepted': True, 'password': 'public-test-fixture'})
        self.assertEqual(response.status, 400)
        self.assertIsNone(state.vm)

    async def test_destructive_option_needs_typed_path_and_password_never_persists(self):
        state = self.app['state']
        state.controller.configuration = demo_configuration()
        self.fake_plan(state, {'id': 'erase:/dev/vda', 'kind': 'erase', 'title': 'erase', 'detail': '', 'revert': 'no',
                               'destructive': True, 'confirm': '/dev/vda', 'fits': True, 'available': 1})
        response = await self.request('/api/build', {'digest': 'plan-digest', 'option': 'erase:/dev/vda', 'accepted': True,
                                                     'confirmation': '/dev/sdz', 'password': 'public-test-fixture', 'memory': 4096, 'cpus': 4})
        self.assertEqual(response.status, 400)
        self.assertIsNone(state.vm)
        state.persist()
        self.assertNotIn('public-test-fixture', state.record.read_text())
        self.assertNotIn('password', json.dumps(state.public()))

    async def test_secure_boot_needs_systemd_boot_and_setup_mode(self):
        state = self.app['state']
        data = DemoProvider().reply('', [])['configuration']
        data['bootloader'] = 'grub'
        state.controller.configuration = Configuration.parse(data)
        response = await self.request('/api/plan', {'memory': 4096, 'secure_boot': True})
        self.assertEqual(response.status, 400)
        self.assertIn('Secure Boot', (await response.json())['error'])
        self.assertIsNone(state.plan)
        config = demo_configuration()
        state.controller.configuration = config
        state.preview = {'option': {'title': 'RAM', 'revert': 'x'}, 'image': {'format': 'qcow2', 'path': '/p'}, 'revert': {'kind': 'ram'}}
        state.disk_ready = True
        body = {'layout': 'erase', 'confirmation': config.disk, 'accepted': True, 'enroll_keys': True}
        for signed, reason in ((False, 'не подписана'), (True, 'Setup Mode')):
            state.built = {'configuration': config.as_dict(), 'consent': state.current_consent(), 'encrypted': False,
                           'secure_boot': signed}
            response = await self.request('/api/final/finalize', body)
            self.assertEqual(response.status, 400)
            self.assertIn(reason, (await response.json())['error'])
            self.assertIsNone(state.final_task)

    async def test_plan_requires_configuration(self):
        response = await self.request('/api/plan', {'memory': 4096})
        self.assertEqual(response.status, 400)

    async def test_finalize_and_revert_require_a_preview(self):
        for path, body in (('/api/final/finalize', {'layout': 'erase', 'confirmation': '/dev/vda', 'accepted': True}), ('/api/revert', {})):
            response = await self.request(path, body)
            self.assertEqual(response.status, 400)
        self.assertIsNone(self.app['state'].final_task)

    async def test_finalization_blocks_other_operations(self):
        state = self.app['state']
        state.final['phase'] = 'working'
        for path in ('/api/resume', '/api/stop', '/api/revert', '/api/build', '/api/plan', '/api/chat'):
            response = await self.request(path, {'text': 'hi'})
            self.assertIn(response.status, (400, 409))
        self.assertIsNone(state.final_task)

    async def test_screenshot_api_is_not_part_of_product(self):
        response = await self.request('/api/screenshot', {})
        self.assertEqual(response.status, 404)

    async def test_runtime_refuses_to_start_outside_live(self):
        import runtime
        with patch.object(runtime, 'DATA_ROOT', Path(self.directory.name)), \
                patch.object(runtime, 'live_environment', return_value=False):
            vm = runtime.VirtualMachine({'format': 'qcow2', 'path': str(Path(self.directory.name) / 'none.qcow2')})
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

    async def test_resume_rejects_path_outside_vm_directory(self):
        state = self.app['state']
        state.controller.configuration = demo_configuration()
        state.disk_ready, state.saved_vm = True, {'directory': '/etc', 'image': {'format': 'raw', 'path': '/dev/null'}}
        state.preview = {'option': {'title': 't', 'revert': 'r'}, 'image': {'format': 'raw', 'path': '/dev/null'}, 'revert': {'kind': 'partition'}}
        state.built = {'configuration': demo_configuration().as_dict(), 'consent': state.current_consent(), 'encrypted': False}
        response = await self.request('/api/resume', {})
        self.assertEqual(response.status, 400)
        self.assertIsNone(state.vm)

    def fake_vm(self, fail=False):
        root = self.directory.name
        class VM:
            def __init__(self, image, *args):
                self.directory = Path(root) / 'vm/web-test'
                self.image = image
                self.running = False
                self.process = SimpleNamespace(pid=4242)
            def describe(self): return {'directory': str(self.directory), 'image': self.image}
            async def start(self, install=True):
                if fail: raise RuntimeError('QEMU failed')
                self.running = True
            async def install(self, config, password, passphrase, notify, hardware=None, secure_boot=False):
                assert hardware is not None and 'gpus' in hardware  # the real computer's inventory reaches the guest
                notify({'kind': 'progress', 'text': 'Installing'})
                notify({'kind': 'installed', 'text': 'Installed'})
            async def stop(self): self.running = False
        return VM

    async def test_successful_build_enables_finalize_and_revert(self):
        state = self.app['state']
        config = demo_configuration()
        state.controller.configuration = config
        option = self.fake_plan(state)
        prepared = {'image': {'format': 'qcow2', 'path': '/var/lib/agi-os/preview/ram/preview.qcow2'}, 'revert': {'kind': 'ram'}}
        state.controller.installing = True
        async def privileged(script, request):
            self.assertEqual(request['op'], 'prepare')
            return prepared
        with patch.object(server, 'VirtualMachine', self.fake_vm()), patch.object(server, 'privileged', privileged):
            await state.build(config, state.current_consent(), option, 'public-test-fixture', 'private-passphrase', 4096, 4)
        self.assertEqual(state.phase, 'ready')
        self.assertTrue(state.disk_ready)
        self.assertTrue(state.built['encrypted'])
        self.assertFalse(state.controller.installing)
        record = state.record.read_text()
        self.assertNotIn('public-test-fixture', record)
        self.assertNotIn('private-passphrase', record)
        self.assertFalse(state.public()['can_finalize'])  # the preview is still running
        await state.vm.stop()
        public = state.public()
        self.assertTrue(public['can_finalize'])
        self.assertTrue(public['can_revert'])
        self.assertFalse(public['can_plan'])

    async def test_failed_installation_is_not_resumable(self):
        state = self.app['state']
        config = demo_configuration()
        state.controller.configuration = config
        option = self.fake_plan(state)
        async def privileged(script, request):
            return {'image': {'format': 'qcow2', 'path': '/x.qcow2'}, 'revert': {'kind': 'ram'}}
        with patch.object(server, 'VirtualMachine', self.fake_vm(fail=True)), patch.object(server, 'privileged', privileged):
            await state.build(config, state.current_consent(), option, 'public-test-fixture', '', 4096, 4)
        self.assertEqual(state.phase, 'error')
        self.assertFalse(state.disk_ready)
        self.assertFalse(state.public()['can_resume'])
        self.assertTrue(state.public()['can_revert'])

    async def test_in_memory_preview_is_forgotten_after_live_restart(self):
        state = self.app['state']
        state.controller.configuration = demo_configuration()
        state.preview = {'option': {'title': 'RAM', 'revert': 'x'}, 'image': {'format': 'qcow2', 'path': '/p'}, 'revert': {'kind': 'ram'}}
        state.built = {'configuration': demo_configuration().as_dict(), 'consent': state.current_consent(), 'encrypted': False}
        state.disk_ready = True
        state.persist()
        state.restore()
        self.assertIsNone(state.preview)
        self.assertIsNone(state.built)
        self.assertFalse(state.disk_ready)


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
