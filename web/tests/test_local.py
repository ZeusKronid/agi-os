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

    async def test_new_vm_keeps_only_the_newest_earlier_vm_directory(self):
        import os
        import runtime
        root = Path(self.directory.name)
        for age, name in enumerate(('web-old', 'web-older', 'web-newest')):
            (root / 'vm' / name).mkdir(parents=True)
            (root / 'vm' / name / 'guest-console.log').write_text('log')
            os.utime(root / 'vm' / name, (1000 - age * 100 if name != 'web-newest' else 2000,) * 2)
        with patch.object(runtime, 'DATA_ROOT', root):
            vm = runtime.VirtualMachine({'format': 'qcow2', 'path': str(root / 'none.qcow2')})
            restored = runtime.VirtualMachine.restore({'directory': str(root / 'vm/web-newest'), 'image': vm.image})
        self.assertEqual(sorted(p.name for p in (root / 'vm').iterdir()), sorted(['web-newest', vm.directory.name]))
        self.assertTrue((restored.directory / 'guest-console.log').exists())  # resuming prunes nothing

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
            async def install(self, config, password, passphrase, notify, hardware=None):
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


class SecretAuditTests(LocalApiTests):
    """No password, passphrase or API key reaches a file of the site, its state or events;
    the preview's logs are removed after a successful finalization and kept otherwise."""
    PASSWORD, PASSPHRASE, KEY = 'audit-user-password', 'audit-luks-passphrase', 'sk-audit-api-key'

    def assert_no_secrets(self):
        state = self.app['state']
        texts = [json.dumps(state.public(), ensure_ascii=False), json.dumps(state.events, ensure_ascii=False)]
        for path in Path(self.directory.name).rglob('*'):
            if path.is_file():
                texts.append(path.read_bytes().decode(errors='replace'))
        for secret in (self.PASSWORD, self.PASSPHRASE, self.KEY):
            for text in texts:
                self.assertNotIn(secret, text)

    def vm_directory(self):
        directory = Path(self.directory.name) / 'vm/web-test'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'qemu.log').write_text('qemu started\n')
        (directory / 'guest-console.log').write_text('guest journal\n')
        return directory

    async def built_preview(self):
        state = self.app['state']
        config = demo_configuration()
        state.controller.configuration = config
        option = self.fake_plan(state)
        state.controller.installing = True

        async def privileged(script, request):
            return {'image': {'format': 'qcow2', 'path': '/var/lib/agi-os/preview/ram/preview.qcow2'},
                    'revert': {'kind': 'ram'}, 'text': 'reverted'}
        with patch.object(server, 'VirtualMachine', self.fake_vm()), patch.object(server, 'privileged', privileged):
            await state.build(config, state.current_consent(), option, self.PASSWORD, self.PASSPHRASE, 4096, 4)
        await state.vm.stop()
        self.vm_directory()
        return state, privileged

    def finalizer(self, events, code=0):
        seen = {}

        class Stream:
            def __init__(self, lines): self.lines = [json.dumps(e).encode() + b'\n' for e in lines]
            def __aiter__(self): return self
            async def __anext__(self):
                if not self.lines: raise StopAsyncIteration
                return self.lines.pop(0)
            async def read(self): return b''

        class Stdin:
            def write(self, data): seen['stdin'] = data
            async def drain(self): pass
            def close(self): pass

        class Process:
            stdin, stdout, stderr = Stdin(), Stream(events), Stream([])
            async def wait(self): return code

        async def spawn(*args, **kwargs):
            return Process()
        return spawn, seen

    async def test_api_key_is_never_stored_or_published(self):
        import provider
        with patch.object(server, 'LiveProvider', provider.LiveProvider):
            response = await self.request('/api/provider', {'kind': 'openai', 'model': 'gpt-test', 'key': self.KEY})
        self.assertEqual(response.status, 200)
        self.assertNotIn(self.KEY, await response.text())
        self.app['state'].persist()
        self.assert_no_secrets()

    async def test_successful_finalization_removes_preview_logs_and_keeps_no_secret(self):
        state, privileged = await self.built_preview()
        self.assert_no_secrets()
        spawn, seen = self.finalizer([{'kind': 'final-progress', 'text': 'copying'},
                                      {'kind': 'finalized', 'mode': 'copy', 'text': 'done'}])
        payload = {'target': '/dev/vda', 'layout': 'erase', 'passphrase': self.PASSPHRASE}
        with patch('asyncio.create_subprocess_exec', spawn), patch.object(server, 'privileged', privileged):
            await server.finalize_task(state, payload)
        self.assertIn(self.PASSPHRASE.encode(), seen['stdin'])  # the root helper still gets it, over stdin only
        self.assertEqual(state.final['phase'], 'complete')
        self.assertNotIn('passphrase', payload)
        self.assertFalse((Path(self.directory.name) / 'vm/web-test').exists())
        self.assertIsNone(state.public()['vm'])
        self.assert_no_secrets()

    async def test_failed_finalization_keeps_preview_logs_for_diagnostics(self):
        state, privileged = await self.built_preview()
        spawn, _ = self.finalizer([{'kind': 'final-error', 'text': 'copy failed'}], code=1)
        with patch('asyncio.create_subprocess_exec', spawn), patch.object(server, 'privileged', privileged):
            await server.finalize_task(state, {'target': '/dev/vda', 'layout': 'erase', 'passphrase': self.PASSPHRASE})
        self.assertEqual(state.final['phase'], 'error')
        self.assertTrue((Path(self.directory.name) / 'vm/web-test/guest-console.log').exists())
        self.assert_no_secrets()

    def test_journal_of_live_is_bounded(self):
        conf = Path(__file__).resolve().parents[2] / 'archiso/airootfs/etc/systemd/journald.conf.d/agi-os-size.conf'
        self.assertIn('RuntimeMaxUse=128M', conf.read_text())


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
