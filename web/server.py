#!/usr/bin/env python3
"""Local AGIOS website: conversation, reversible preview, installation onto the computer's disk."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

from aiohttp import web

from settings import SOURCE_ROOT as ROOT, ENGINE, DATA_ROOT, FONTS, GUACAMOLE_JS
sys.path.insert(0, str(ENGINE))
from controller import Controller
from domain import Configuration, ValidationError
from english import english
from providers import APIProvider, ProviderError, PROVIDERS
from worker import packages_for
from runtime import VirtualMachine
from guacamole import tunnel

from provider import LiveProvider, connect_chatgpt
from system import live_environment
from deployment import consent as consent_binding, orphan_previews, target_inventory

GIB = 2**30


async def privileged(script, request):
    """Run a root helper of this site with one JSON request; secrets travel only over stdin."""
    process = await asyncio.create_subprocess_exec(
        'sudo', '-n', '/usr/bin/python', '-B', str(ROOT / 'web' / script),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await process.communicate(json.dumps({**request, 'data_root': str(DATA_ROOT)}).encode() + b'\n')
    try:
        answer = json.loads(out.decode() or '{}')
    except ValueError:
        answer = {}
    if 'error' in answer:
        raise ValidationError(answer['error'])
    if process.returncode or 'result' not in answer:
        raise ValidationError('The storage operation did not finish: ' + err.decode(errors='replace')[-800:])
    return answer['result']


class State:
    def __init__(self, guacd_port):
        self.guacd_port = guacd_port
        self.messages = []
        self.events = []
        self.status = 'Describe the system you want'
        self.phase = 'idle'
        self.error = None
        self.vm = None
        self.build_task = None
        self.final_task = None
        self.plan = None
        self.lock = asyncio.Lock()
        self.provider = LiveProvider()
        self.controller = Controller(target_inventory(), self.provider, notify=self.notify)
        self.record = DATA_ROOT / 'session.json'
        self.restore()

    def notify(self, kind, value):
        if kind == 'status':
            self.status = english(value)

    def refresh_inventory(self):
        self.controller.snapshot = target_inventory()
        return self.controller.snapshot

    def persist(self):
        self.record.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = {'messages': self.messages, 'history': self.controller.history,
                'configuration': self.controller.configuration.as_dict() if self.controller.configuration else None,
                'vm': self.vm.describe() if self.vm else self.saved_vm,
                'disk_ready': self.disk_ready, 'built': self.built, 'preview': self.preview, 'final': self.final}
        temp = self.record.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False))
        temp.chmod(0o600)
        temp.replace(self.record)

    def restore(self):
        self.saved_vm = None
        self.disk_ready = False
        self.built = None    # {'configuration', 'consent', 'encrypted'} of the system in the preview
        self.preview = None  # {'option', 'image', 'revert', 'monitor', 'budget'} from storage_worker
        self.final = {'phase': 'idle', 'events': []}
        if self.record.exists():
            data = json.loads(self.record.read_text())
            self.messages = data['messages']
            self.controller.history = data['history']
            if data.get('configuration'):
                self.controller.configuration = Configuration.parse(data['configuration'])
            self.saved_vm = data.get('vm')
            self.disk_ready = data.get('disk_ready', False)
            self.built = data.get('built')
            self.preview = data.get('preview')
            self.final = data.get('final', {'phase': 'idle', 'events': []})
            if self.final['phase'] == 'working':
                self.final.update(phase='error', error='Finishing the installation was interrupted. Check the disk; success is not confirmed.')
            if self.final['phase'] == 'complete':
                self.phase, self.status = 'finalized', 'Ready to boot from this computer’s disk'
            elif self.preview and self.preview.get('revert', {}).get('kind') == 'ram' and not Path(self.preview['image']['path']).exists():
                # Memory does not survive a Live restart: the preview is gone, the disks were never touched.
                self.preview, self.built, self.disk_ready, self.saved_vm = None, None, False, None

    def current_consent(self):
        config = self.controller.configuration
        if not config:
            return None
        try:
            return consent_binding(config, self.controller.snapshot)
        except ValidationError as exc:
            return {'error': str(exc), 'target': config.disk}

    def public(self):
        config = self.controller.configuration
        consent = self.current_consent()
        snapshot = self.controller.snapshot
        running = bool(self.vm and self.vm.running)
        busy = self.controller.installing or self.final['phase'] == 'working'
        built = None
        if self.built:
            built_config = Configuration.parse(self.built['configuration'])
            built = {'summary': built_config.summary(self.built['consent']['disk']), 'target': self.built['consent']['target'],
                     'encrypted': self.built['encrypted'], 'digest': self.built['consent']['digest'],
                     'storage': self.preview['option']['title'] if self.preview else None,
                     'on_target': bool(self.preview and self.preview['image']['format'] == 'raw'
                                       and self.preview['image']['path'].startswith(self.built['consent']['target'])),
                     'revert': self.preview['option']['revert'] if self.preview else None}
        current = self.preview['image']['path'] if self.preview else None
        return {'messages': self.messages, 'status': self.status, 'phase': self.phase,
                'error': self.error, 'model': self.provider.model,
                'firmware': snapshot['firmware'], 'orphans': orphan_previews(snapshot, current),
                'disks': [{k: d.get(k) for k in ('path', 'size', 'model', 'serial', 'eligible', 'reason', 'partitions')} for d in snapshot['disks']],
                'configuration': config.as_dict() if config else None,
                'summary': config.summary(consent['disk']) if config and consent and 'disk' in consent else None,
                'consent': consent, 'plan': self.plan, 'events': self.events[-100:], 'running': running,
                'console_id': self.vm.process.pid if running else None,
                'vm': self.vm.describe() if self.vm else self.saved_vm,
                'can_plan': bool(config and consent and 'digest' in consent and not running and not busy and not self.preview),
                'can_resume': bool(self.disk_ready and not running and not busy and self.final['phase'] != 'complete'),
                'can_revert': bool(self.preview and not busy and not running and self.final['phase'] != 'complete'),
                'built': built,
                'can_finalize': bool(self.disk_ready and self.built and self.preview and not running and not busy and self.final['phase'] != 'complete'),
                'final': self.final}

    async def monitor_memory(self):
        """Stop an in-memory preview before the zram budget is exhausted."""
        monitor, budget = self.preview.get('monitor'), self.preview.get('budget')
        while monitor and self.vm and self.vm.running:
            try:
                used = int(Path(monitor).read_text().split()[2])
            except (OSError, ValueError, IndexError):
                return
            if used > budget * 0.97:
                self.error = 'The preview ran out of RAM; the installation stopped. Pick another place for the preview.'
                await self.vm.stop()
                return
            await asyncio.sleep(2)

    async def build(self, config, consent, option, password, passphrase, memory, cpus):
        watchdog = None
        try:
            self.phase, self.status = 'starting', 'Preparing preview storage: ' + option['title']
            self.disk_ready = False
            self.built = None
            self.final = {'phase': 'idle', 'events': []}
            self.persist()
            prepared = await privileged('storage_worker.py', {'op': 'prepare', 'option': option, 'needed': self.plan['needed'],
                                                              'vm_memory': memory * 2**20, 'target': config.disk,
                                                              'compression': self.plan['compression']})
            self.preview = {'option': option, **prepared}
            self.vm = VirtualMachine(prepared['image'], memory, cpus)
            self.persist()
            self.status = 'Starting the installer VM'
            await self.vm.start()
            if prepared.get('monitor'):
                watchdog = asyncio.create_task(self.monitor_memory())
            self.phase, self.status = 'installing', 'Waiting for the installer inside the VM'
            def event(value):
                # The installer inside the VM speaks the shared engine's Russian; the website speaks English.
                if 'text' in value:
                    value = {**value, 'text': english(value['text'])}
                self.events.append(value)
                self.status = value.get('text', self.status)
            await self.vm.install(config, password, passphrase, event)
            self.phase, self.status = 'ready', 'Installed in the preview and booted'
            self.disk_ready = True
            self.built = {'configuration': config.as_dict(), 'consent': consent, 'encrypted': bool(passphrase)}
        except asyncio.CancelledError:
            self.phase, self.status = 'stopped', 'VM stopped. The installation did not finish'
            raise
        except Exception as exc:
            self.phase, self.status = 'error', 'The installation did not finish'
            self.error = self.error or english(str(exc)) or 'The VM timed out'
        finally:
            password = passphrase = None
            if watchdog:
                watchdog.cancel()
            self.controller.installing = False
            self.persist()


@web.middleware
async def local_only(request, handler):
    # A local website still must reject requests from unrelated browser origins.
    if request.host not in request.app['hosts']:
        raise web.HTTPForbidden(text='Localhost only')
    origin = request.headers.get('Origin')
    if origin and origin != f'http://{request.host}':
        raise web.HTTPForbidden(text='Invalid origin')
    if request.method == 'POST' and request.headers.get('X-AGIOS') != 'local':
        raise web.HTTPForbidden(text='Missing local request header')
    try:
        return await handler(request)
    except (ValidationError, ProviderError, ValueError, KeyError) as exc:
        return web.json_response({'error': english(str(exc))}, status=400)


async def index(request):
    return web.FileResponse(ROOT / 'web/static/index.html')


async def guacamole_script(request):
    return web.FileResponse(GUACAMOLE_JS)


async def state_get(request):
    return web.json_response(request.app['state'].public())


def not_busy(state):
    if state.lock.locked() or state.controller.installing or state.final['phase'] == 'working':
        raise web.HTTPConflict(text='Wait for the current operation to finish')


async def chat(request):
    state = request.app['state']
    not_busy(state)
    data = await request.json()
    text = data.get('text', '')
    if not isinstance(text, str) or not text.strip() or len(text) > 16000:
        raise ValidationError('Write a message of up to 16000 characters')
    async with state.lock:
        if state.controller.installing:
            raise web.HTTPConflict(text='Wait for the installation to finish')
        state.error = None
        state.messages.append({'role': 'user', 'content': text})
        state.status = 'The agent is thinking about the configuration…'
        try:
            await asyncio.to_thread(state.refresh_inventory)
            reply = await asyncio.to_thread(state.controller.respond, text)
            state.messages.append({'role': 'assistant', 'content': reply['message'], 'suggestions': reply['suggestions']})
            state.status = 'Configuration ready: next, find room for the preview' if state.controller.configuration else 'Let’s keep talking'
            state.plan = None
        except Exception as exc:
            state.error = english(str(exc))
            state.status = 'The agent did not reply'
        state.persist()
    return web.json_response(state.public())


async def configure(request):
    state = request.app['state']
    not_busy(state)
    data = await request.json()
    async with state.lock:
        kind = data.get('kind', 'chatgpt')
        if kind == 'chatgpt':
            state.status = 'Finish signing in in the new browser tab'
            provider = await asyncio.to_thread(connect_chatgpt, data.get('model') or None)
        else:
            provider = APIProvider(kind, data.get('endpoint') or PROVIDERS[kind][1], data.get('key', ''))
            provider.model = data.get('model', '').strip()
            if not provider.model:
                raise ValidationError('Enter a model')
            provider = LiveProvider(provider)
        await asyncio.to_thread(state.provider.close)
        state.provider = state.controller.provider = provider
    return web.json_response(state.public())


def vm_size(data):
    memory, cpus = data.get('memory', 4096), data.get('cpus', 4)
    if type(memory) is not int or not 2048 <= memory <= 32768 or type(cpus) is not int or not 1 <= cpus <= 16:
        raise ValidationError('Use 2–32 GiB of RAM and 1–16 CPUs')
    return memory, cpus


async def plan(request):
    """Estimate the system size and list reversible places for the preview."""
    state = request.app['state']
    not_busy(state)
    data = await request.json()
    async with state.lock:
        if not state.public()['can_plan']:
            raise ValidationError('Agree on a configuration with the agent first, or remove the current preview')
        memory, _ = vm_size(data)
        encrypt = data.get('encrypt') is True
        config = state.controller.configuration
        state.status = 'Measuring the system and looking for room for the preview…'
        await asyncio.to_thread(state.refresh_inventory)
        consent = consent_binding(config, state.controller.snapshot)
        estimate = await asyncio.to_thread(state.controller.catalog.estimate, packages_for(config))
        needed = int(estimate['installed'] * 1.2) + 2 * GIB
        # LUKS output is incompressible: an encrypted in-memory preview needs its full size.
        compression = 1.0 if encrypt else 1.3
        probe = await privileged('storage_worker.py', {'op': 'probe', 'needed': needed, 'target': config.disk,
                                                       'vm_memory': memory * 2**20, 'compression': compression})
        digest = hashlib.sha256(json.dumps({'consent': consent['digest'], 'needed': needed, 'memory': memory, 'encrypt': encrypt,
                                            'options': [o['id'] for o in probe['options']]}, sort_keys=True).encode()).hexdigest()
        state.plan = {'digest': digest, 'estimate': estimate, 'needed': needed, 'memory': memory, 'encrypt': encrypt,
                      'compression': compression, 'options': probe['options'], 'consent': consent['digest']}
        state.status = 'Pick where the preview lives and confirm'
        return web.json_response(state.public())


def secret_text(value, name, low, high):
    if not isinstance(value, str) or not low <= len(value) <= high or any(c in value for c in '\n\r\0'):
        raise ValidationError(f'{name}: {low} to {high} characters without line breaks')
    return value


async def build(request):
    state = request.app['state']
    not_busy(state)
    if state.vm and state.vm.running:
        raise web.HTTPConflict(text='Stop the current VM before a new installation')
    data = await request.json()
    async with state.lock:
        if state.controller.installing or (state.vm and state.vm.running) or state.preview:
            raise web.HTTPConflict(text='Remove the current preview first')
        config = state.controller.configuration
        if not config or not state.plan:
            raise ValidationError('Find room for the preview first')
        await asyncio.to_thread(state.refresh_inventory)
        consent = consent_binding(config, state.controller.snapshot)
        if data.get('digest') != state.plan['digest'] or state.plan['consent'] != consent['digest']:
            raise ValidationError('The configuration, disk or storage options changed. Find room again')
        option = next((o for o in state.plan['options'] if o['id'] == data.get('option')), None)
        if not option or not option['fits']:
            raise ValidationError('Pick a place for the preview that fits')
        if data.get('accepted') is not True:
            raise ValidationError('Confirm the chosen place')
        if option['destructive'] and data.get('confirmation') != option['confirm']:
            raise ValidationError('For this option, type the exact path: ' + option['confirm'])
        password = secret_text(data.get('password', ''), 'User password', 8, 256)
        passphrase = ''
        if state.plan['encrypt']:
            passphrase = secret_text(data.get('passphrase', ''), 'Encryption password', 8, 512)
        memory, cpus = vm_size(data)
        if memory != state.plan['memory']:
            raise ValidationError('VM memory changed; find room again')
        state.error = None
        state.events = []
        state.controller.installing = True
        state.build_task = asyncio.create_task(state.build(config, consent, option, password, passphrase, memory, cpus))
        return web.json_response({'accepted': True}, status=202)


async def stop(request):
    state = request.app['state']
    if state.lock.locked() or state.final['phase'] == 'working':
        raise web.HTTPConflict(text='Wait for the current operation to finish')
    async with state.lock:
        if state.build_task and not state.build_task.done():
            state.build_task.cancel()
            await asyncio.gather(state.build_task, return_exceptions=True)
        if state.vm:
            await state.vm.stop()
        if state.disk_ready:
            state.phase, state.status = 'stopped', 'VM stopped. The preview is kept'
        state.persist()
        return web.json_response(state.public())


async def resume(request):
    state = request.app['state']
    if state.lock.locked() or state.final['phase'] == 'working':
        raise web.HTTPConflict(text='Wait for the current operation to finish')
    async with state.lock:
        if not state.public()['can_resume']:
            raise ValidationError('No stopped preview')
        if not state.vm:
            state.vm = VirtualMachine.restore(state.saved_vm)
        await state.vm.start(install=False)
        state.phase, state.status = 'ready', 'The preview is running again'
        state.persist()
        return web.json_response(state.public())


async def release_preview(state):
    """Undo the preview storage and forget the preview; disks return to their prior state."""
    result = await privileged('storage_worker.py', {'op': 'revert', 'state': state.preview['revert']})
    state.preview, state.built, state.disk_ready, state.saved_vm, state.vm = None, None, False, None, None
    state.events = []
    return result


async def revert(request):
    state = request.app['state']
    if state.lock.locked() or state.final['phase'] == 'working':
        raise web.HTTPConflict(text='Wait for the current operation to finish')
    async with state.lock:
        if not state.preview or state.final['phase'] == 'complete':
            raise ValidationError('No preview to remove')
        if state.build_task and not state.build_task.done():
            state.build_task.cancel()
            await asyncio.gather(state.build_task, return_exceptions=True)
        if state.vm:
            await state.vm.stop()
        result = await release_preview(state)
        state.phase, state.status, state.error = 'idle', result['text'], None
        state.persist()
        return web.json_response(state.public())


async def remove_orphan(request):
    """Delete a preview partition left by an earlier session; other partitions stay untouched."""
    state = request.app['state']
    not_busy(state)
    data = await request.json()
    async with state.lock:
        snapshot = await asyncio.to_thread(state.refresh_inventory)
        current = state.preview['image']['path'] if state.preview else None
        orphan = next((o for o in orphan_previews(snapshot, current) if o['device'] == data.get('device')), None)
        if orphan is None:
            raise ValidationError('No such preview partition')
        result = await privileged('storage_worker.py', {'op': 'revert', 'state': {'kind': 'partition', 'disk': orphan['disk'], 'device': orphan['device']}})
        await asyncio.to_thread(state.refresh_inventory)
        state.status = result['text']
        return web.json_response(state.public())


async def finalize_task(state, payload):
    state.final = {'phase': 'working', 'target': payload['target'], 'layout': payload['layout'], 'events': []}
    state.persist()
    try:
        process = await asyncio.create_subprocess_exec(
            'sudo', '-n', '/usr/bin/python', '-B', str(ROOT / 'web/finalize_worker.py'),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        process.stdin.write(json.dumps(payload).encode() + b'\n')
        await process.stdin.drain()
        process.stdin.close()
        payload.pop('passphrase', None)
        stderr_task = asyncio.create_task(process.stderr.read())
        complete, mode = False, None
        async for line in process.stdout:
            event = json.loads(line)
            state.final['events'].append(event)
            state.status = event.get('text', state.status)
            if event['kind'] == 'finalized':
                complete, mode = True, event.get('mode')
            if event['kind'] == 'final-error':
                state.final['error'] = event['text']
        code = await process.wait()
        stderr = (await stderr_task).decode(errors='replace')
        if code or not complete:
            raise ValidationError(state.final.get('error') or stderr[-1500:] or 'Finishing did not complete')
        if mode == 'copy':
            # The copy is verified; the temporary preview storage is no longer needed.
            result = await privileged('storage_worker.py', {'op': 'revert', 'state': state.preview['revert']})
            state.final['events'].append({'kind': 'final-progress', 'text': 'Temporary preview storage removed: ' + result['text']})
        state.final['phase'] = 'complete'
        state.phase, state.status = 'finalized', 'Ready to boot from this computer’s disk'
    except Exception as exc:
        state.final.update(phase='error', error=str(exc))
        state.status = 'Installing to disk did not finish'
    finally:
        payload.pop('passphrase', None)
        state.controller.installing = False
        state.persist()


async def finalize(request):
    state = request.app['state']
    data = await request.json()
    async with state.lock:
        if not state.public()['can_finalize']:
            raise ValidationError('Install the system in the preview first and shut it down from its power menu')
        built = state.built
        layout = data.get('layout')
        if layout not in ('erase', 'alongside'):
            raise ValidationError('Choose: erase the disk or install alongside other systems')
        if data.get('confirmation') != built['consent']['target'] or data.get('accepted') is not True:
            raise ValidationError('Confirm the installation and type the exact disk path: ' + built['consent']['target'])
        await asyncio.to_thread(state.refresh_inventory)
        current = consent_binding(Configuration.parse(built['configuration']), state.controller.snapshot)
        if current['fingerprint'] != built['consent']['fingerprint']:
            raise ValidationError('The target disk changed after you confirmed')
        passphrase = ''
        if built['encrypted']:
            passphrase = secret_text(data.get('passphrase', ''), 'Encryption password', 8, 512)
        payload = {'target': built['consent']['target'], 'fingerprint': built['consent']['fingerprint'],
                   'configuration': built['configuration'], 'passphrase': passphrase,
                   'image': state.preview['image'], 'layout': layout, 'confirmation': data['confirmation']}
        # Mark synchronously before scheduling, preventing a concurrent second submission.
        state.controller.installing = True
        state.final = {'phase': 'working', 'target': payload['target'], 'layout': layout, 'events': []}
        state.final_task = asyncio.create_task(finalize_task(state, payload))
        return web.json_response({'accepted': True}, status=202)


async def power(request):
    state = request.app['state']
    data = await request.json()
    if state.final['phase'] != 'complete' or state.controller.installing:
        raise ValidationError('Finish installing to the computer’s disk first')
    if not live_environment():
        raise ValidationError('Power actions work only inside Live')
    action = data.get('action')
    if action not in ('poweroff', 'reboot'):
        raise ValidationError('Unknown action')
    proc = await asyncio.create_subprocess_exec('sudo', '-n', 'shutdown', '-h' if action == 'poweroff' else '-r', '+1')
    if await proc.wait():
        raise ValidationError('Could not schedule the power action')
    message = ('Live powers off in a minute. Remove the stick and power on the computer: it boots from the installed disk.'
               if action == 'poweroff' else 'The computer restarts in a minute. Remove the AGIOS stick so the installed system boots.')
    return web.json_response({'scheduled': True, 'message': message})


async def cleanup(app):
    state = app['state']
    if state.final_task and not state.final_task.done():
        await asyncio.shield(state.final_task)
    if state.build_task and not state.build_task.done():
        state.build_task.cancel()
        await asyncio.gather(state.build_task, return_exceptions=True)
    if state.vm:
        await state.vm.stop()
    await asyncio.to_thread(state.provider.close)


def application(port=8787, guacd_port=14822):
    app = web.Application(middlewares=[local_only], client_max_size=1_000_000)
    app['state'] = State(guacd_port)
    app['hosts'] = {f'localhost:{port}', f'127.0.0.1:{port}'}
    app.router.add_get('/api/state', state_get)
    app.router.add_post('/api/chat', chat)
    app.router.add_post('/api/provider', configure)
    app.router.add_post('/api/plan', plan)
    app.router.add_post('/api/build', build)
    app.router.add_post('/api/stop', stop)
    app.router.add_post('/api/resume', resume)
    app.router.add_post('/api/revert', revert)
    app.router.add_post('/api/orphans/remove', remove_orphan)
    app.router.add_post('/api/final/finalize', finalize)
    app.router.add_post('/api/final/power', power)
    app.router.add_get('/tunnel', tunnel)
    app.router.add_get('/', index)
    app.router.add_static('/static', ROOT / 'web/static')
    if FONTS.is_dir():
        app.router.add_static('/fonts', FONTS)
    app.router.add_get('/guacamole.js', guacamole_script)
    app.on_cleanup.append(cleanup)
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--guacd-port', type=int, default=14822)
    args = parser.parse_args()
    if not live_environment():
        parser.error('The AGIOS website runs inside the booted Live environment. To test, boot the Live ISO in QEMU.')
    os.umask(0o077)
    web.run_app(application(args.port, args.guacd_port), host='127.0.0.1', port=args.port, access_log=None, shutdown_timeout=5)
