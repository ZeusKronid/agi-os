import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server  # noqa: F401  (puts the installer engine on sys.path)
import diagnostics
import journal
from aiohttp.test_utils import AioHTTPTestCase
from controller import DemoProvider
from test_local import live_demo_inventory

FAKE_KEY = 'sk-' + 'proj-' + 'FAKE' * 5  # built at runtime: not a real key format for scanners
SECRETS = ('hunter2-long', FAKE_KEY, 'luks-passphrase-1', 'abcdefghijklmnop')


def fake_command(args, timeout=30):
    if args[0] == 'journalctl':
        records = [{'__REALTIME_TIMESTAMP': '1', 'SYSLOG_IDENTIFIER': 'agios-web', 'PRIORITY': '6',
                    'MESSAGE': 'connected with key ' + FAKE_KEY, 'AGIOS_OPERATION': 'build-0123456789ab',
                    'AGIOS_DATA': '{"password": "hunter2-long"}', '_CMDLINE': 'not exported'},
                   {'__REALTIME_TIMESTAMP': '2', 'SYSLOG_IDENTIFIER': 'kernel', 'MESSAGE': [104, 105]}]
        return '\n'.join(json.dumps(r) for r in records) + '\nnot json\n', ''
    if args[0] == 'pacman':
        return 'linux 6.9.1-1\npython 3.13.1-1\n', ''
    return '', ''


def unpack(data):
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        return {m.name.removeprefix('agios-diagnostics/'): archive.extractfile(m).read().decode() for m in archive.getmembers()}


class BundleTests(unittest.TestCase):
    def test_bundle_contents_are_secret_free(self):
        with tempfile.TemporaryDirectory() as root, patch.object(diagnostics, 'command', fake_command):
            data_root = Path(root)
            (data_root / 'session.json').write_text(json.dumps({
                'messages': [{'role': 'user', 'content': 'мой пароль password=hunter2-long'}],
                'configuration': {'username': 'tester', 'passphrase': 'luks-passphrase-1'}}))
            vm = data_root / 'vm/web-20260923-120000-abcdef'
            vm.mkdir(parents=True)
            (vm / 'qemu.log').write_text('x' * (diagnostics.LOG_TAIL + 10) + '\nqemu ok\n')
            (vm / 'guest-console.log').write_text('chpasswd tester:$6$saltsalt$abcdefghijklmnop\n')
            (data_root / 'source-revision').write_text('6ee8e2a\n')
            inventory = live_demo_inventory()
            inventory['disks'][0]['serial'] = 'S4EVNX0N123456'
            files = unpack(diagnostics.bundle({'phase': 'error', 'error': 'Bearer abcdefghijklmnop'}, inventory, data_root, data_root))
        self.assertTrue({'README.txt', 'versions.json', 'state.json', 'inventory.json', 'session.json',
                         'journal-agios.jsonl', 'journal-services.jsonl', 'journal-warnings.jsonl',
                         'vm/web-20260923-120000-abcdef/qemu.log', 'vm/web-20260923-120000-abcdef/guest-console.log'} <= set(files))
        everything = '\n'.join(files.values())
        for secret in SECRETS:
            self.assertNotIn(secret, everything)
        self.assertNotIn('S4EVNX0N123456', everything)
        self.assertIn('…3456', files['inventory.json'])
        versions = json.loads(files['versions.json'])
        self.assertEqual((versions['source_revision'], versions['packages']['linux']), ('6ee8e2a', '6.9.1-1'))
        first, second = [json.loads(line) for line in files['journal-agios.jsonl'].splitlines()]
        self.assertEqual(first['AGIOS_OPERATION'], 'build-0123456789ab')
        self.assertNotIn('_CMDLINE', first)
        self.assertEqual(second['MESSAGE'], 'hi')
        self.assertTrue(files['vm/web-20260923-120000-abcdef/qemu.log'].startswith('[… начало обрезано'))
        self.assertIn('tester', files['session.json'])

    def test_unreadable_journal_is_explained(self):
        with tempfile.TemporaryDirectory() as root, \
                patch.object(diagnostics, 'command', return_value=('', 'No journal files were opened due to insufficient permissions.')):
            files = unpack(diagnostics.bundle({}, {}, Path(root), Path(root)))
        self.assertIn('Журнал недоступен', files['journal-agios.jsonl'])


class StorageHelperLogTests(unittest.TestCase):
    def test_output_of_commands_fed_on_stdin_is_not_logged(self):
        import storage_worker
        records = []
        with patch.object(journal, 'sink', records.append):
            with self.assertRaises(Exception):
                storage_worker.sh(['sh', '-c', 'cat >&2; exit 3'], input_text='stdin-secret-value')
            with self.assertRaises(Exception):
                storage_worker.sh(['sh', '-c', 'echo visible-detail >&2; exit 3'], input_text=None)
        self.assertNotIn('stdin-secret-value', json.dumps(records))
        self.assertEqual([r['AGIOS_EVENT'] for r in records], ['command.failed', 'command.failed'])

    def test_sort_like_keys_are_not_masked(self):
        self.assertEqual(journal.redact({'sort_key': 1, 'api_key': 'x'}), {'sort_key': 1, 'api_key': '***'})


class DiagnosticsApiTests(AioHTTPTestCase):
    async def get_application(self):
        self.directory = tempfile.TemporaryDirectory()
        self.records = []
        (Path(self.directory.name) / 'web/static').mkdir(parents=True)
        for target, value in (('ROOT', Path(self.directory.name)), ('LiveProvider', DemoProvider),
                              ('DATA_ROOT', Path(self.directory.name)), ('target_inventory', live_demo_inventory)):
            patcher = patch.object(server, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (patch.object(diagnostics, 'command', fake_command), patch.object(journal, 'sink', self.records.append)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.directory.cleanup)
        return server.application()

    async def test_export_requires_local_post_and_returns_archive(self):
        response = await self.client.post('/api/diagnostics', headers={'Host': 'localhost:8787'})
        self.assertEqual(response.status, 403)
        response = await self.client.get('/api/diagnostics', headers={'Host': 'localhost:8787'})
        self.assertEqual(response.status, 405)
        response = await self.client.post('/api/diagnostics', headers={'Host': 'localhost:8787', 'X-AGIOS': 'local'})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content_type, 'application/gzip')
        self.assertRegex(response.headers['Content-Disposition'], r'attachment; filename="agios-diagnostics-\d{8}-\d{6}\.tar\.gz"')
        files = unpack(await response.read())
        state = json.loads(files['state.json'])
        self.assertNotIn('messages', state)
        self.assertIn('phase', state)
        self.assertIn('diagnostics.exported', [r['AGIOS_EVENT'] for r in self.records])

    async def test_rejected_requests_are_logged(self):
        response = await self.client.post('/api/chat', json={'text': ''}, headers={'Host': 'localhost:8787', 'X-AGIOS': 'local'})
        self.assertEqual(response.status, 400)
        rejected = [r for r in self.records if r['AGIOS_EVENT'] == 'api.rejected']
        self.assertEqual(json.loads(rejected[0]['AGIOS_DATA'])['path'], '/api/chat')

    async def test_helper_requests_carry_the_operation(self):
        sent = {}

        class Process:
            returncode = 0

            async def communicate(self, data):
                sent.update(json.loads(data))
                return json.dumps({'result': {'ok': True}}).encode(), b''

        async def spawn(*args, **kwargs):
            return Process()

        async def run():
            journal.operation.set('build-0123456789ab')
            return await server.privileged('storage_worker.py', {'op': 'probe'})

        with patch.object(server.asyncio, 'create_subprocess_exec', spawn):
            self.assertEqual(await server.asyncio.create_task(run()), {'ok': True})
        self.assertEqual(sent['trace'], 'build-0123456789ab')
        events = [(r['AGIOS_EVENT'], r.get('AGIOS_OPERATION')) for r in self.records]
        self.assertEqual(events, [('helper.start', 'build-0123456789ab'), ('helper.done', 'build-0123456789ab')])


if __name__ == '__main__':
    unittest.main()
