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

    async def test_chatgpt_sign_in_page_is_handed_to_the_browser_tab(self):
        # The site runs as a system user without the desktop: no xdg-open, the page opens the URL.
        seen = []
        state = self.app['state']

        def connect(model, show_login):
            show_login('file:///etc/shadow')
            seen.append(state.login_url)
            show_login('https://auth.openai.com/oauth/authorize?state=x')
            seen.append(state.login_url)
            return DemoProvider()
        with patch.object(server, 'connect_chatgpt', connect):
            response = await self.request('/api/provider', {'kind': 'chatgpt'})
        self.assertEqual(response.status, 200)
        self.assertEqual(seen, [None, 'https://auth.openai.com/oauth/authorize?state=x'])
        self.assertIsNone((await response.json())['login_url'])

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
            self.assertEqual(request['op'], 'prepare')  # an in-memory preview keeps no record
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

    async def test_failed_file_check_goes_back_to_the_model(self):
        state = self.app['state']
        data = DemoProvider().reply('', [])['configuration']
        data['home_files'] = [{'path': '.config/foot/foot.ini', 'content': '[colors]\nbogus=1\n'}]
        config = Configuration.parse(data)
        state.controller.configuration = config
        state.controller.history = [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': '{}'}]
        option = self.fake_plan(state)
        files = state.public()['files']
        self.assertEqual(files[0]['display'], '~/.config/foot/foot.ini')
        self.assertIn('foot', files[0]['checks'])
        failure = server.CONFIG_CHECK_FAILED + ':\n~/.config/foot/foot.ini — foot:\ninvalid section name: colors'
        VM = self.fake_vm()
        async def install(self, *args, **kwargs):
            raise RuntimeError(failure)
        async def privileged(script, request):
            return {'image': {'format': 'qcow2', 'path': '/x.qcow2'}, 'revert': {'kind': 'ram'}}
        with patch.object(VM, 'install', install), patch.object(server, 'VirtualMachine', VM), \
             patch.object(server, 'privileged', privileged):
            await state.build(config, state.current_consent(), option, 'public-test-fixture', '', 4096, 4)
        self.assertEqual(state.phase, 'error')
        self.assertEqual(state.error, failure)
        self.assertEqual(state.controller.history[-1]['role'], 'user')
        self.assertIn('invalid section name', state.controller.history[-1]['content'])
        self.assertIn('агента', state.status)

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


class PreviewRecordApiTests(AioHTTPTestCase):
    """A preview kept on a medium survives a Live restart through its record."""
    get_application, request = LocalApiTests.get_application, LocalApiTests.request
    fake_plan, fake_vm = LocalApiTests.fake_plan, LocalApiTests.fake_vm

    def partition_option(self):
        return {'id': 'part:/dev/vda:2048', 'kind': 'partition', 'title': 'Новый раздел', 'detail': '',
                'revert': 'Удалить одну запись раздела', 'destructive': False, 'confirm': None, 'fits': True,
                'available': 20 * 2**30}

    async def build_on_partition(self, fail=False):
        state = self.app['state']
        config = demo_configuration()
        state.controller.configuration = config
        option = self.fake_plan(state, self.partition_option())
        marks = []
        async def privileged(script, request):
            if request['op'] == 'prepare':
                return {'image': {'format': 'raw', 'path': '/dev/vda2'},
                        'revert': {'kind': 'partition', 'disk': '/dev/vda', 'device': '/dev/vda2'}}
            self.assertEqual(request['op'], 'mark')
            self.assertEqual(request['revert']['device'], '/dev/vda2')
            marks.append(json.loads(json.dumps(request['record'])))
            return {'marked': True}
        state.controller.installing = True
        with patch.object(server, 'VirtualMachine', self.fake_vm(fail=fail)), patch.object(server, 'privileged', privileged):
            await state.build(config, state.current_consent(), option, 'public-test-fixture', 'private-passphrase', 4096, 4)
            if state.record_task:
                await state.record_task
        return marks

    async def test_build_records_progress_without_secrets(self):
        marks = await self.build_on_partition()
        self.assertEqual(marks[0]['status'], 'installing')
        self.assertEqual(marks[-1]['status'], 'ready')
        self.assertTrue(marks[-1]['encrypted'])
        texts = [e['text'] for e in marks[-1]['journal']]
        self.assertIn('Система установлена в превью', texts)
        self.assertTrue(any('Installing' in t for t in texts))
        dump = json.dumps(marks)
        self.assertNotIn('public-test-fixture', dump)
        self.assertNotIn('private-passphrase', dump)
        self.assertEqual(marks[-1]['target']['serial'], 'DEMO-ONLY')

    async def test_failed_build_is_recorded_as_unfinished(self):
        marks = await self.build_on_partition(fail=True)
        self.assertEqual(marks[-1]['status'], 'failed')
        self.assertIn('QEMU failed', marks[-1]['error'])

    def found(self, status='ready', **record_changes):
        from test_preview_record import sample_record
        record = sample_record(status=status, **record_changes)
        record['target'].update(path='/dev/sdz', size=64 * 2**30, model='Демонстрационный диск', serial='DEMO-ONLY', wwn='')
        import preview_record
        return {'id': 'partition:/dev/vda2', 'kind': 'partition', 'disk': '/dev/vda', 'device': '/dev/vda2',
                'size': 20 * 2**30, 'medium': 'Disk', 'problem': None, 'record': preview_record.clean(record)}

    async def test_found_previews_offer_the_right_actions(self):
        state = self.app['state']
        state.found = [self.found('ready'), {**self.found('failed'), 'id': 'file:/dev/sdb1', 'device': '/dev/sdb1'},
                       {'id': 'partition:/dev/vda3', 'kind': 'partition', 'disk': '/dev/vda', 'device': '/dev/vda3',
                        'size': 1, 'medium': 'Disk', 'problem': 'Записи превью нет', 'record': None}]
        found = {f['id']: f for f in state.public()['found']}
        self.assertTrue(found['partition:/dev/vda2']['can_continue'])
        self.assertFalse(found['partition:/dev/vda2']['can_retry'])
        self.assertTrue(found['file:/dev/sdb1']['can_retry'])
        self.assertFalse(found['file:/dev/sdb1']['can_continue'])
        self.assertFalse(found['partition:/dev/vda3']['can_continue'] or found['partition:/dev/vda3']['can_retry'])
        self.assertTrue(found['partition:/dev/vda3']['can_remove'])

    async def test_continue_rebinds_the_target_and_enables_finalize(self):
        state = self.app['state']
        entry = self.found('ready')
        state.found = [entry]
        calls = []
        async def privileged(script, request):
            calls.append(request['op'])
            if request['op'] == 'adopt':
                self.assertEqual(request['id'], 'partition:/dev/vda2')
                return {'image': {'format': 'raw', 'path': '/dev/vda2'}, 'medium': 'Disk', 'record': entry['record'],
                        'revert': {'kind': 'partition', 'disk': '/dev/vda', 'device': '/dev/vda2'}}
            return {'marked': True}
        with patch.object(server, 'VirtualMachine', self.fake_vm()), patch.object(server, 'privileged', privileged):
            response = await self.request('/api/previews/continue', {'id': 'partition:/dev/vda2'})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(calls, ['adopt', 'mark'])
        public = state.public()
        # The record named /dev/sdz; the same disk is /dev/vda after the restart.
        self.assertEqual(state.controller.configuration.disk, '/dev/vda')
        self.assertEqual(public['built']['target'], '/dev/vda')
        self.assertTrue(public['built']['encrypted'])
        self.assertTrue(public['can_finalize'])
        self.assertTrue(public['can_resume'])
        self.assertTrue(public['can_revert'])
        self.assertEqual(public['found'], [])
        self.assertEqual(state.preview['record']['status'], 'ready')

    async def test_continue_refuses_unfinished_or_foreign_previews(self):
        state = self.app['state']
        async def privileged(script, request):
            raise AssertionError('the medium must not be touched')
        with patch.object(server, 'privileged', privileged):
            state.found = [self.found('failed')]
            response = await self.request('/api/previews/continue', {'id': 'partition:/dev/vda2'})
            self.assertEqual(response.status, 400)
            state.found = [self.found('ready', firmware='bios')]
            response = await self.request('/api/previews/continue', {'id': 'partition:/dev/vda2'})
            self.assertEqual(response.status, 400)
            self.assertIn('BIOS', (await response.json())['error'])
            entry = self.found('ready')
            entry['record']['target']['serial'] = 'OTHER'
            state.found = [entry]
            response = await self.request('/api/previews/continue', {'id': 'partition:/dev/vda2'})
            self.assertEqual(response.status, 400)
        self.assertIsNone(state.preview)

    async def test_retry_restores_configuration_and_removes_storage(self):
        state = self.app['state']
        state.found = [self.found('installing')]
        calls = []
        async def privileged(script, request):
            calls.append(request['op'])
            if request['op'] == 'remove':
                return {'reverted': True, 'text': 'Раздел превью удалён'}
            return {'found': []}
        with patch.object(server, 'privileged', privileged):
            response = await self.request('/api/previews/retry', {'id': 'partition:/dev/vda2'})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(calls, ['remove', 'scan'])
        public = state.public()
        self.assertEqual(public['configuration']['disk'], '/dev/vda')
        self.assertTrue(public['can_plan'])
        self.assertIsNone(state.preview)
        self.assertEqual(json.loads(state.controller.history[-1]['content'])['configuration']['disk'], '/dev/vda')

    async def test_restored_configuration_keeps_roles_alternating(self):
        state = self.app['state']
        state.controller.history = [{'role': 'user', 'content': 'unanswered'}]
        state.restore_conversation(demo_configuration(), 'restored')
        self.assertEqual([m['role'] for m in state.controller.history], ['user', 'assistant'])
        state.restore_conversation(demo_configuration(), 'again')
        self.assertEqual([m['role'] for m in state.controller.history], ['user', 'assistant', 'user', 'assistant'])

    async def test_remove_found_preview(self):
        state = self.app['state']
        state.found = [self.found('ready')]
        async def privileged(script, request):
            if request['op'] == 'remove':
                return {'reverted': True, 'text': 'Раздел превью удалён'}
            return {'found': []}
        with patch.object(server, 'privileged', privileged):
            response = await self.request('/api/previews/remove', {'id': 'partition:/dev/vda2'})
            self.assertEqual(response.status, 200)
            response = await self.request('/api/previews/remove', {'id': 'partition:/dev/vda9'})
            self.assertEqual(response.status, 400)
        self.assertEqual(state.status, 'Раздел превью удалён')

    async def test_site_restart_during_installation_is_not_a_success(self):
        state = self.app['state']
        state.controller.configuration = demo_configuration()
        state.preview = {'option': {'title': 'Раздел', 'revert': 'x'}, 'image': {'format': 'raw', 'path': '/dev/vda2'},
                         'revert': {'kind': 'partition'}}
        state.persist()
        state.restore()
        self.assertEqual(state.phase, 'error')
        public = state.public()
        self.assertFalse(public['can_finalize'] or public['can_resume'])
        self.assertTrue(public['can_revert'])
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
