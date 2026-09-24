"""The conversation on the page (CMP-129): steps while waiting, cancel, a kept configuration
and an explicit rebuild when the agent changed the system after the preview was built."""
import asyncio
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from aiohttp.test_utils import AioHTTPTestCase
from controller import DemoCatalog, DemoProvider
from domain import Configuration
from system import demo_inventory


def live_demo_inventory():
    snapshot = demo_inventory()
    snapshot['live'] = True
    return snapshot


def demo_configuration():
    return Configuration.parse(DemoProvider().reply('', [])['configuration'])


def question():
    return {'message': 'Which browser?', 'suggestions': ['Firefox'], 'lookup': [], 'configuration': None}


class DialogApiTests(AioHTTPTestCase):
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

    async def request(self, path, body):
        return await self.client.post(path, json=body, headers={'Host': 'localhost:8787', 'X-AGIOS': 'local'})

    def use(self, provider):
        state = self.app['state']
        state.provider = state.controller.provider = provider
        state.controller.catalog = DemoCatalog()
        return state

    async def test_question_keeps_the_agreed_configuration_and_plan(self):
        state = self.use(DemoProvider())
        response = await self.request('/api/chat', {'text': 'Sway, please'})
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertIsNotNone(body['configuration'])
        self.assertFalse(body['configuration_kept'])
        state.plan = {'digest': 'kept'}
        state.controller.provider.reply = lambda system, messages: question()
        body = await (await self.request('/api/chat', {'text': 'Add a browser?'})).json()
        self.assertTrue(body['configuration_kept'])
        self.assertIsNotNone(body['configuration'])
        self.assertEqual(body['plan'], {'digest': 'kept'})
        self.assertIn('unchanged', body['status'])
        self.assertIsNone(body['turn'])

    async def test_cancel_removes_the_message_and_changes_nothing(self):
        started, release = threading.Event(), threading.Event()

        class Slow:
            model = 'slow'
            def reply(self, system, messages):
                started.set()
                release.wait(10)
                return DemoProvider().reply(system, messages)
            def close(self): pass

        state = self.use(Slow())
        chat = asyncio.ensure_future(self.request('/api/chat', {'text': 'Build me Sway'}))
        while not started.is_set():
            await asyncio.sleep(.02)
        body = await (await self.client.get('/api/state', headers={'Host': 'localhost:8787'})).json()
        self.assertEqual([step['text'] for step in body['turn']['steps']], ['Asking the model'])
        self.assertEqual(body['messages'][-1]['content'], 'Build me Sway')
        response = await self.request('/api/chat/cancel', {})
        self.assertEqual(response.status, 200)
        body = await (await chat).json()
        release.set()
        self.assertEqual(body['cancelled'], 'Build me Sway')
        self.assertEqual(body['messages'], [])
        self.assertIsNone(body['configuration'])
        self.assertIsNone(body['turn'])
        await asyncio.sleep(.1)  # the abandoned answer arrives late and is discarded
        self.assertIsNone(state.controller.configuration)
        self.assertEqual(state.controller.history, [])

    async def test_cancel_without_a_request_is_refused(self):
        response = await self.request('/api/chat/cancel', {})
        self.assertEqual(response.status, 400)

    async def test_rebuild_is_needed_when_the_configuration_changed_after_the_build(self):
        state = self.app['state']
        config = demo_configuration()
        state.controller.configuration = config
        state.built = {'configuration': config.as_dict(), 'consent': state.current_consent(), 'encrypted': False}
        state.preview = {'option': {'title': 'RAM', 'revert': 'nothing'}, 'image': {'format': 'qcow2', 'path': '/x'}, 'revert': {'kind': 'ram'}}
        self.assertFalse(state.public()['rebuild_needed'])
        state.controller.configuration = Configuration.parse({**config.as_dict(), 'hostname': 'changed'})
        self.assertTrue(state.public()['rebuild_needed'])
        state.final = {'phase': 'complete', 'events': []}
        self.assertFalse(state.public()['rebuild_needed'])

    async def test_copy_percentages_replace_each_other(self):
        import json
        state = self.app['state']
        events = [{'kind': 'final-progress', 'text': 'Opening the preview for checking'},
                  {'kind': 'final-progress', 'text': 'Copying: 0%', 'step': 'copy', 'percent': 0},
                  {'kind': 'final-progress', 'text': 'Copying: 40%', 'step': 'copy', 'percent': 40},
                  {'kind': 'final-progress', 'text': 'Copying: 100%', 'step': 'copy', 'percent': 100},
                  {'kind': 'final-progress', 'text': 'Verifying the copy by checksums'},
                  {'kind': 'finalized', 'mode': 'promote', 'text': 'done'}]

        class Stream:
            def __init__(self, lines): self.lines = [json.dumps(e).encode() + b'\n' for e in lines]
            def __aiter__(self): return self
            async def __anext__(self):
                if not self.lines: raise StopAsyncIteration
                return self.lines.pop(0)
            async def read(self): return b''

        class Stdin:
            def write(self, data): pass
            async def drain(self): pass
            def close(self): pass

        class Process:
            stdin, stdout, stderr = Stdin(), Stream(events), Stream([])
            async def wait(self): return 0

        async def spawn(*args, **kwargs):
            return Process()
        with patch('asyncio.create_subprocess_exec', spawn):
            await server.finalize_task(state, {'target': '/dev/vda', 'layout': 'erase', 'passphrase': ''})
        texts = [event['text'] for event in state.final['events']]
        self.assertEqual(texts[:3], ['Opening the preview for checking', 'Copying: 100%', 'Verifying the copy by checksums'])
        self.assertEqual(state.final['phase'], 'complete')

    def test_copy_reports_each_new_percent_once(self):
        import finalize_worker
        emitted = []
        with patch.object(finalize_worker, 'emit', lambda kind, **data: emitted.append(data)):
            output = finalize_worker.copy_progress('Copying')
            for chunk in ('  1,024   0%  1MB/s\r', '  2,048   3%\r  4,096   7%', ' 7%\r', 'garbage', '100%'):
                output(chunk)
        self.assertEqual([e['percent'] for e in emitted], [7, 100])
        self.assertEqual(emitted[-1], {'text': 'Copying: 100%', 'step': 'copy', 'percent': 100})
