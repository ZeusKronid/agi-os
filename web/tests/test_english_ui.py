"""What the website shows is English: its state, its errors and the preview records it writes (CMP-150)."""
import json
import re
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_local  # puts the website and the engine on the import path
import server
from aiohttp.test_utils import AioHTTPTestCase
from controller import DemoProvider
from domain import Configuration
from hardware import demo
import preview_record

CYRILLIC = re.compile('[Ѐ-ԯ]')


def found_entry(status, **record_changes):
    config = DemoProvider().reply('', [])['configuration']
    record = {'version': preview_record.VERSION, 'id': 'a1b2c3', 'status': status, 'created': '2026-09-24T10:00:00+0300',
              'updated': '2026-09-24T10:30:00+0300', 'error': None, 'configuration': config, 'encrypted': True,
              'firmware': 'uefi', 'secure_boot': False,
              'target': {'path': '/dev/sdz', 'size': 64 * 2**30, 'model': 'Demo disk', 'serial': 'DEMO-ONLY', 'wwn': ''},
              'hardware': demo(), 'vm': {'memory': 4096, 'cpus': 4},
              'storage': {'kind': 'partition', 'title': 'New partition', 'revert': 'Delete one partition entry'},
              'journal': [{'time': 't', 'text': 'Preview storage prepared'}]}
    record.update(record_changes)
    return {'id': 'partition:/dev/vda2', 'kind': 'partition', 'disk': '/dev/vda', 'device': '/dev/vda2',
            'size': 20 * 2**30, 'medium': 'Disk', 'problem': None, 'record': preview_record.clean(record)}


class EnglishWebsiteTests(AioHTTPTestCase):
    get_application, request = test_local.LocalApiTests.get_application, test_local.LocalApiTests.request
    fake_plan, fake_vm = test_local.LocalApiTests.fake_plan, test_local.LocalApiTests.fake_vm
    build_on_partition = test_local.PreviewRecordApiTests.build_on_partition

    def partition_option(self):
        return {'id': 'part:/dev/vda:2048', 'kind': 'partition', 'title': 'New partition', 'detail': '',
                'revert': 'Delete one partition entry', 'destructive': False, 'confirm': None, 'fits': True,
                'available': 20 * 2**30}

    def assertEnglish(self, value, context=''):
        text = json.dumps(value, ensure_ascii=False)
        self.assertIsNone(CYRILLIC.search(text), f'{context}: {text[:600]}')

    async def rejected(self, path, body):
        response = await self.request(path, body)
        self.assertEqual(response.status, 400, path)
        answer = await response.json()
        self.assertEnglish(answer, path)
        return answer['error']

    async def test_state_with_hardware_files_login_and_found_previews(self):
        state = self.app['state']
        data = DemoProvider().reply('', [])['configuration']
        data.update(swap='hibernate', home_files=[
            {'path': '.config/autostart/sync.desktop', 'content': '[Desktop Entry]\nType=Application\nName=Sync\nExec=syncthing\n'},
            {'path': '.config/foot/foot.ini', 'content': '[main]\nfont=monospace:size=11\n'}],
            system_files=[{'path': 'etc/systemd/logind.conf.d/lid.conf', 'content': '[Login]\nHandleLidSwitch=suspend\n'}])
        state.controller.configuration = Configuration.parse(data)
        state.controller.snapshot['hardware'] = {**demo(), 'secure_boot': True, 'setup_mode': True}
        self.fake_plan(state)
        state.found = [found_entry('ready'), {**found_entry('failed', error='The VM timed out'), 'id': 'file:/dev/sdb1', 'device': '/dev/sdb1'},
                       {**found_entry('installing'), 'id': 'file:/dev/sdc1', 'device': '/dev/sdc1'},
                       {'id': 'partition:/dev/vda3', 'kind': 'partition', 'disk': '/dev/vda', 'device': '/dev/vda3',
                        'size': 1, 'medium': 'Disk', 'problem': 'The preview record is damaged', 'record': None}]
        public = state.public()
        self.assertTrue(public['login'] and public['files'] and public['hardware']['lines'] and public['summary'])
        self.assertEqual(len(public['found']), 4)
        self.assertEnglish(public, 'state')

    async def test_rejections_are_english(self):
        state = self.app['state']
        await self.rejected('/api/chat', {'text': ''})
        await self.rejected('/api/plan', {})
        await self.rejected('/api/build', {'digest': 'x', 'option': 'ram'})
        await self.rejected('/api/final/finalize', {})
        await self.rejected('/api/previews/continue', {'id': 'nothing'})
        data = DemoProvider().reply('', [])['configuration']
        data['home_files'] = [{'path': '.config/autostart/x.desktop', 'content': '[Desktop Entry]\nType=Application\nName=X\nExec=x\n'}]
        state.controller.configuration = Configuration.parse(data)
        self.fake_plan(state)
        # The start-up programs were not reviewed.
        await self.rejected('/api/build', {'digest': 'plan-digest', 'option': 'ram', 'accepted': True, 'password': 'public-test-fixture'})
        await self.rejected('/api/plan', {'secure_boot': True, 'memory': 4096})
        async def untouched(script, request):
            raise AssertionError('the medium must not be touched')
        with patch.object(server, 'privileged', untouched):
            for entry in (found_entry('failed'), found_entry('ready', firmware='bios')):
                state.found = [entry]
                await self.rejected('/api/previews/continue', {'id': entry['id']})
            foreign = found_entry('ready')
            foreign['record']['target']['serial'] = 'OTHER'
            state.found = [foreign]
            await self.rejected('/api/previews/continue', {'id': foreign['id']})
            await self.rejected('/api/previews/retry', {'id': foreign['id']})

    async def test_build_status_events_and_record_are_english(self):
        state = self.app['state']
        marks = await self.build_on_partition()
        self.assertEnglish(marks, 'record')
        self.assertEnglish(state.public(), 'after build')
        marks = await self.build_on_partition(fail=True)
        self.assertEnglish(marks, 'failed record')
        self.assertEnglish(state.public(), 'after failed build')

    async def test_restored_and_retried_previews_are_english(self):
        state = self.app['state']
        entry = found_entry('ready')
        state.found = [entry]
        async def privileged(script, request):
            if request['op'] == 'adopt':
                return {'image': {'format': 'raw', 'path': '/dev/vda2'}, 'medium': 'Disk', 'record': entry['record'],
                        'revert': {'kind': 'partition', 'disk': '/dev/vda', 'device': '/dev/vda2'}}
            if request['op'] == 'remove':
                return {'text': 'Removed the preview partition'}
            if request['op'] == 'scan':
                return {'found': []}
            return {'marked': True}
        with patch.object(server, 'VirtualMachine', self.fake_vm()), patch.object(server, 'privileged', privileged):
            response = await self.request('/api/previews/continue', {'id': entry['id']})
            self.assertEqual(response.status, 200, await response.text())
            self.assertEnglish(await response.json(), 'continued')
            self.assertEnglish(state.preview['record'], 'continued record')
            await self.rejected('/api/previews/remove', {'id': 'nothing'})
            await self.rejected('/api/final/finalize', {'layout': 'erase', 'confirmation': '/dev/vda', 'accepted': True, 'enroll_keys': True})
            await state.vm.stop()
            response = await self.request('/api/stop', {})
            self.assertEnglish(await response.json(), 'stopped')
            state.preview, state.built, state.disk_ready, state.vm = None, None, False, None
            retry = {**found_entry('failed'), 'id': 'file:/dev/sdb1', 'device': '/dev/sdb1'}
            state.found = [retry]
            response = await self.request('/api/previews/retry', {'id': retry['id']})
            self.assertEqual(response.status, 200, await response.text())
            self.assertEnglish(await response.json(), 'retried')
        state.preview = {'option': {'title': 'New partition', 'revert': 'x'}, 'image': {'format': 'raw', 'path': '/dev/vda2'},
                         'revert': {'kind': 'partition'}}
        state.disk_ready = False
        state.persist()
        state.restore()
        self.assertEqual(state.phase, 'error')
        self.assertEnglish(state.public(), 'interrupted preview after restart')
