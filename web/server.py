#!/usr/bin/env python3
"""Local AGIOS website: conversation, reversible preview, installation onto the computer's disk."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid

from aiohttp import web

from settings import SOURCE_ROOT as ROOT, ENGINE, DATA_ROOT, FONTS, GUACAMOLE_JS
sys.path.insert(0, str(ENGINE))
from controller import Cancelled, Controller, Turn
from domain import Configuration, ValidationError, hibernation_swap_size
from providers import APIProvider, ProviderError, PROVIDERS
from worker import CONFIG_CHECK_FAILED, packages_for
from configcheck import summary as file_checks
from hardware import describe, driver_plan, profile, virtual
from runtime import VirtualMachine
from guacamole import tunnel
from journal import Logger, new_operation, operation as current_operation
import diagnostics

from provider import LiveProvider, connect_chatgpt
from system import live_environment
from deployment import consent as consent_binding, target_inventory
import preview_record
import release

GIB = 2**30
log = Logger('web')


def traced(request):
    """Attach the current operation id so root helpers log under the same correlation id."""
    trace = current_operation.get()
    return {**request, 'trace': trace} if trace else request


async def privileged(script, request):
    """Run a root helper of this site with one JSON request; secrets travel only over stdin."""
    started = time.monotonic()
    op = request.get('op')
    log.info('helper.start', f'{script} {op}', helper=script, op=op)
    process = await asyncio.create_subprocess_exec(
        'sudo', '-n', '/usr/bin/python', '-B', str(ROOT / 'web' / script),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await process.communicate(json.dumps(traced(request)).encode() + b'\n')
    try:
        answer = json.loads(out.decode() or '{}')
    except ValueError:
        answer = {}
    elapsed = round(time.monotonic() - started, 2)
    if 'error' in answer:
        log.warning('helper.error', f'{script} {op}: {answer["error"]}', helper=script, op=op, seconds=elapsed, code=process.returncode)
        raise ValidationError(answer['error'])
    if process.returncode or 'result' not in answer:
        detail = err.decode(errors='replace')[-800:]
        log.error('helper.failed', f'{script} {op}: exit code {process.returncode}', helper=script, op=op, seconds=elapsed,
                  code=process.returncode, stderr=detail)
        raise ValidationError('The storage operation did not finish: ' + detail)
    log.info('helper.done', f'{script} {op}: done in {elapsed} s', helper=script, op=op, seconds=elapsed)
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
        self.turn = None         # the running request to the model, cancellable from the page
        self.turn_stop = asyncio.Event()
        self.login_url = None
        self.provider = LiveProvider()
        self.controller = Controller(target_inventory(), self.provider, notify=self.notify)
        self.record = DATA_ROOT / 'session.json'
        self.found = []          # previews of earlier Live sessions found on the media
        self.scan_error = None
        self.scan_task = None
        self.record_task = None  # background write of the preview record
        self.record_dirty = False
        self.restore()

    def notify(self, kind, value):
        if kind == 'status':
            self.status = value

    def refresh_inventory(self):
        self.controller.snapshot = target_inventory()
        return self.controller.snapshot

    def new_record(self, config, consent, option, prepared, encrypted, hardware, memory, cpus):
        if option['kind'] == 'ram':
            return None  # Memory does not survive a restart; there is nothing to find again.
        storage = {'kind': option['kind'], 'title': option['title'], 'revert': option['revert']}
        if option['kind'] == 'shrink':
            undo = prepared['revert']
            storage.update(shrunk_start=undo['start'], original_end=undo['original_end'], fstype=undo['fstype'])
        return {'version': preview_record.VERSION, 'id': uuid.uuid4().hex, 'status': 'installing',
                'created': preview_record.now(), 'updated': preview_record.now(), 'error': None,
                'configuration': config.as_dict(), 'encrypted': encrypted, 'firmware': consent['firmware'],
                'secure_boot': bool(self.plan and self.plan.get('secure_boot')),
                'target': preview_record.disk_identity(consent['disk']), 'hardware': hardware,
                'vm': {'memory': memory, 'cpus': cpus}, 'storage': storage, 'journal': []}

    def journal(self, text, status=None, error=None):
        """Update the preview record kept in the preview storage (survives a Live restart)."""
        record = self.preview and self.preview.get('record')
        if not record:
            return False
        record['journal'] = [*record['journal'], {'time': preview_record.now(), 'text': text}][-preview_record.JOURNAL:]
        record['updated'] = preview_record.now()
        if status:
            record['status'], record['error'] = status, error
        self.record_dirty = True
        return True

    def journal_later(self, text):
        """Progress entries are written in the background, one write at a time."""
        if self.journal(text) and not (self.record_task and not self.record_task.done()):
            self.record_task = asyncio.create_task(self.flush_record())

    async def flush_record(self):
        while self.record_dirty and self.preview and self.preview.get('record'):
            self.record_dirty = False
            try:
                await privileged('storage_worker.py', {'op': 'mark', 'record': self.preview['record'],
                                                       'revert': self.preview['revert']})
            except (ValidationError, OSError) as exc:
                warning = 'The preview record was not saved to its storage: ' + str(exc) + '. After a Live restart, this preview can’t be continued.'
                if not self.events or self.events[-1].get('text') != warning:
                    self.events.append({'kind': 'warning', 'text': warning})

    async def save_record(self, text, status=None, error=None):
        """Write the record now (after any write in flight)."""
        if self.record_task and not self.record_task.done():
            await asyncio.gather(self.record_task, return_exceptions=True)
        if self.journal(text, status, error):
            await self.flush_record()

    async def drop_record_task(self):
        if self.record_task and not self.record_task.done():
            self.record_task.cancel()
            await asyncio.gather(self.record_task, return_exceptions=True)
        self.record_dirty = False

    async def scan(self):
        """Look for previews of earlier Live sessions on this computer's media."""
        try:
            result = await privileged('storage_worker.py', {'op': 'scan'})
            self.found, self.scan_error = result['found'], None
        except (ValidationError, OSError) as exc:
            self.found, self.scan_error = [], 'Could not look for previews from earlier sessions: ' + str(exc)

    def found_public(self):
        current = self.preview['image']['path'] if self.preview else None
        medium = self.preview['revert'].get('device') if self.preview else None
        busy = self.controller.installing or self.final['phase'] == 'working' or bool(self.vm and self.vm.running)
        result = []
        for entry in self.found:
            if entry['device'] in (current, medium):
                continue
            record = entry.get('record')
            status = record['status'] if record else None
            item = {k: entry.get(k) for k in ('id', 'kind', 'device', 'disk', 'size', 'medium', 'problem')}
            item.update(status=status, can_continue=False, can_retry=False, can_remove=not busy)
            if record:
                config = record['configuration']
                item['title'] = f"{config['hostname']} · {config['desktop']} · user {config['username']}"
                item['created'] = record['created']
                item['storage'] = record['storage']['title']
                item['target'] = record['target']['path']
                item['encrypted'] = record['encrypted']
                item['error'] = record['error']
                item['journal'] = [e['text'] for e in record['journal'][-8:]]
                free = not busy and not self.preview
                item['can_continue'] = free and status in ('ready', 'finalizing')
                item['can_retry'] = free and status in ('installing', 'failed')
            result.append(item)
        return result

    def found_entry(self, found_id):
        entry = next((e for e in self.found if e['id'] == found_id), None)
        if entry is None:
            raise ValidationError('No such preview; refresh the list')
        return entry

    def rebind(self, record):
        """The record's configuration bound to this computer's current view of its target disk."""
        snapshot = self.refresh_inventory()
        if record['firmware'] != snapshot['firmware']:
            raise ValidationError('The preview was installed for ' + record['firmware'].upper()
                                  + ' boot, but Live is now booted in ' + snapshot['firmware'].upper() + ' mode')
        matches = [d for d in snapshot['disks'] if preview_record.same_disk(record['target'], d)]
        if len(matches) > 1:
            matches = [d for d in matches if d['path'] == record['target']['path']]
        if len(matches) != 1:
            raise ValidationError('This preview’s target disk (' + record['target']['path'] + ') was not found')
        config = Configuration.parse({**record['configuration'], 'disk': matches[0]['path']})
        return config, consent_binding(config, snapshot)

    def restore_conversation(self, config, text):
        """Give the agreed configuration back to the conversation (and to the model's context)."""
        reply = {'message': text, 'suggestions': [], 'lookup': [], 'configuration': config.as_dict()}
        if not self.controller.history or self.controller.history[-1]['role'] != 'user':
            self.controller.history.append({'role': 'user', 'content': 'Restored the configuration of an earlier preview (data).'})
        self.controller.history.append({'role': 'assistant', 'content': json.dumps(reply, ensure_ascii=False)})
        self.controller.configuration = config
        self.messages.append({'role': 'assistant', 'content': text, 'suggestions': []})

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
                try:
                    self.controller.configuration = Configuration.parse(data['configuration'])
                except ValidationError:
                    pass  # Stricter checks of a newer engine: the proposal must be agreed again.
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
            elif self.preview and not self.disk_ready:
                # The site stopped during the installation into the preview: never a silent success.
                self.phase = 'error'
                self.status = 'Installing into the preview did not finish'
                self.error = 'Installing into the preview was interrupted. Remove the preview and build it again.'

    def current_consent(self):
        config = self.controller.configuration
        if not config:
            return None
        try:
            return consent_binding(config, self.controller.snapshot)
        except ValidationError as exc:
            return {'error': str(exc), 'target': config.disk}

    def rebuild_needed(self, config):
        """The agent changed the configuration after the preview was built: the preview
        (and Install) still hold the previous one until the user rebuilds explicitly."""
        return bool(config and self.built and self.final['phase'] != 'complete'
                    and Configuration.parse(self.built['configuration']).digest() != config.digest())

    def public(self):
        config = self.controller.configuration
        consent = self.current_consent()
        snapshot = self.controller.snapshot
        running = bool(self.vm and self.vm.running)
        busy = self.controller.installing or self.final['phase'] == 'working'
        built = None
        if self.built:
            built_config = Configuration.parse(self.built['configuration'])
            built = {'summary': built_config.summary(self.built['consent']['disk'], self.built.get('hardware')), 'target': self.built['consent']['target'],
                     'encrypted': self.built['encrypted'], 'digest': self.built['consent']['digest'],
                     'secure_boot': bool(self.built.get('secure_boot')),
                     'storage': self.preview['option']['title'] if self.preview else None,
                     'on_target': bool(self.preview and self.preview['image']['format'] == 'raw'
                                       and self.preview['image']['path'].startswith(self.built['consent']['target'])),
                     'revert': self.preview['option']['revert'] if self.preview else None}
        return {'messages': self.messages, 'status': self.status, 'phase': self.phase,
                'error': self.error, 'model': self.provider.model, 'provider': getattr(self.provider, 'label', ''),
                'login_url': self.login_url,
                'firmware': snapshot['firmware'], 'found': self.found_public(),
                'scanning': bool(self.scan_task and not self.scan_task.done()), 'scan_error': self.scan_error,
                'disks': [{k: d.get(k) for k in ('path', 'size', 'model', 'serial', 'eligible', 'reason', 'partitions')} for d in snapshot['disks']],
                'configuration': config.as_dict() if config else None,
                'configuration_kept': bool(config and self.controller.kept),
                'turn': self.turn.public() if self.turn else None,
                'rebuild_needed': self.rebuild_needed(config),
                'files': config_files(config),
                'summary': config.summary(consent['disk'], snapshot['hardware']) if config and consent and 'disk' in consent else None,
                'login': config.login_entries() if config else [],
                'hardware': self.hardware_public(config),
                'consent': consent, 'plan': self.plan, 'events': self.events[-100:], 'running': running,
                'console_id': self.vm.process.pid if running else None,
                'vm': self.vm.describe() if self.vm else self.saved_vm,
                'can_plan': bool(config and consent and 'digest' in consent and not running and not busy and not self.preview),
                'can_resume': bool(self.disk_ready and not running and not busy and self.final['phase'] != 'complete'),
                'can_revert': bool(self.preview and not busy and not running and self.final['phase'] != 'complete'),
                'built': built,
                'can_finalize': bool(self.disk_ready and self.built and self.preview and not running and not busy and self.final['phase'] != 'complete'),
                'final': self.final}

    def hardware_public(self, config):
        """The real computer for the page: inventory lines, the drivers the engine adds,
        and what the preview on virtual devices cannot check."""
        hardware = profile(self.controller.snapshot['hardware'])
        plan = driver_plan(hardware, config.packages if config else (), config.session if config else '')
        return {'lines': describe(hardware), 'packages': plan['packages'], 'services': plan['services'],
                'secure_boot': hardware['secure_boot'], 'setup_mode': hardware['setup_mode'],
                'notes': plan['notes'], 'unverified': plan['unverified'], 'configured': bool(config), 'virtual': virtual(hardware)}

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
        current_operation.set(new_operation('build'))
        log.info('build.start', 'Building the preview: ' + option['title'], option=option['id'], kind=option.get('kind'),
                 memory=memory, cpus=cpus, encrypted=bool(passphrase), configuration=config.digest())
        secure_boot = bool(self.plan and self.plan.get('secure_boot'))
        try:
            self.phase, self.status = 'starting', 'Preparing preview storage: ' + option['title']
            self.disk_ready = False
            self.built = None
            self.final = {'phase': 'idle', 'events': []}
            self.persist()
            prepared = await privileged('storage_worker.py', {'op': 'prepare', 'option': option, 'needed': self.plan['needed'],
                                                              'sparse': self.plan.get('sparse', 0),
                                                              'vm_memory': memory * 2**20, 'target': config.disk,
                                                              'compression': self.plan['compression']})
            hardware = profile(self.controller.snapshot['hardware'])
            self.preview = {'option': option, **prepared,
                            'record': self.new_record(config, consent, option, prepared, bool(passphrase), hardware, memory, cpus)}
            self.vm = VirtualMachine(prepared['image'], memory, cpus)
            self.persist()
            await self.save_record('Preview storage prepared: ' + option['title'])
            self.status = 'Starting the installer VM'
            await self.vm.start()
            if prepared.get('monitor'):
                watchdog = asyncio.create_task(self.monitor_memory())
            self.phase, self.status = 'installing', 'Waiting for the installer inside the VM'
            stages = set()
            def event(value):
                self.events.append(value)
                self.status = value.get('text', self.status)
                log.log('error' if value.get('kind') == 'error' else 'info', 'build.event.' + str(value.get('kind')),
                        str(value.get('text', '')), stage=value.get('stage'))
                if value.get('stage') not in stages and value.get('text'):
                    stages.add(value.get('stage'))
                    self.journal_later(value['text'])
            await self.vm.install(config, password, passphrase, event, hardware, secure_boot)
            self.phase, self.status = 'ready', 'Installed in the preview and booted'
            self.disk_ready = True
            self.built = {'configuration': config.as_dict(), 'consent': consent, 'encrypted': bool(passphrase), 'hardware': hardware,
                          'secure_boot': secure_boot}
            log.info('build.ready', 'Installed in the preview and booted', vm=str(self.vm.directory))
            await self.save_record('System installed in the preview', status='ready')
        except asyncio.CancelledError:
            self.phase, self.status = 'stopped', 'VM stopped. The installation did not finish'
            log.warning('build.cancelled', 'Preview build stopped')
            self.journal('Installing into the preview stopped', status='failed', error=self.status)
            raise
        except Exception as exc:
            self.phase, self.status = 'error', 'The installation did not finish'
            self.error = self.error or str(exc) or 'The VM timed out'
            log.error('build.failed', self.error, exc=exc, vm=str(self.vm.directory) if self.vm else None)
            await self.save_record('Installing into the preview did not finish', status='failed', error=self.error)
            if str(exc).startswith(CONFIG_CHECK_FAILED):
                # The model wrote these files: it receives the checker output with the next message.
                self.controller.report_check_failure(str(exc))
                self.status = 'The settings files did not pass the check. Ask the agent to fix them — it sees the error.'
        finally:
            password = passphrase = None
            if watchdog:
                watchdog.cancel()
            self.controller.installing = False
            self.persist()


def config_files(config):
    """The files the model wrote, for a separate review block: the user sees exactly
    what lands on disk and which checks guard it."""
    if not config:
        return []
    return [{'scope': scope, 'path': path, 'display': prefix + path, 'content': content,
             'checks': file_checks(scope, path)}
            for scope, prefix, files in (('home', '~/', config.home_files), ('system', '/', config.system_files))
            for path, content in files]


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
    started = time.monotonic()
    try:
        response = await handler(request)
    except (ValidationError, ProviderError, ValueError, KeyError) as exc:
        log.warning('api.rejected', f'{request.path}: {exc}', path=request.path, error=type(exc).__name__)
        return web.json_response({'error': str(exc)}, status=400)
    except web.HTTPException as exc:
        log.warning('api.refused', f'{request.path}: {exc.status} {exc.text}', path=request.path, status=exc.status)
        raise
    except Exception as exc:
        log.error('api.crashed', f'{request.path}: internal error {type(exc).__name__}', exc=exc, path=request.path)
        raise
    if request.method == 'POST':
        log.info('api.request', f'{request.path} → {response.status}', path=request.path, status=response.status,
                 seconds=round(time.monotonic() - started, 2))
    return response


async def index(request):
    return web.FileResponse(ROOT / 'web/static/index.html')


async def guacamole_script(request):
    return web.FileResponse(GUACAMOLE_JS)


async def state_get(request):
    return web.json_response(request.app['state'].public())


async def version_get(request):
    return web.json_response(release.current())


async def version_check(request):
    # Only on the user's explicit request: the Live never contacts the release server by itself.
    return web.json_response(await asyncio.to_thread(release.check))


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
        message = {'role': 'user', 'content': text}
        state.messages.append(message)
        state.status = 'The agent is thinking about the configuration…'
        turn = state.turn = Turn(lambda value: state.notify('status', value))
        state.turn_stop.clear()
        stopper = asyncio.ensure_future(state.turn_stop.wait())
        try:
            await asyncio.to_thread(state.refresh_inventory)
            work = asyncio.ensure_future(asyncio.to_thread(state.controller.respond, text, turn))
            await asyncio.wait({work, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if not work.done():
                # Cancelled from the page. The controller refuses to commit this turn, so a
                # late answer (an API request cannot be interrupted) changes nothing.
                work.add_done_callback(lambda task: task.exception())
                raise Cancelled('cancelled')
            reply = work.result()
            state.messages.append({'role': 'assistant', 'content': reply['message'], 'suggestions': reply['suggestions']})
            kept = state.controller.kept
            state.status = ('Configuration unchanged: the agent’s reply did not change it' if kept
                            else 'Configuration changed: rebuild the preview to try it' if state.rebuild_needed(state.controller.configuration)
                            else 'Configuration ready: next, find room for the preview' if state.controller.configuration
                            else 'Let’s keep talking')
            if not kept:
                state.plan = None
        except Cancelled:
            # The message goes back to the input box; the conversation is as before it.
            state.turn = None
            state.messages = [m for m in state.messages if m is not message]
            state.status = 'Request cancelled. Nothing changed'
            log.info('chat.cancelled', 'Request to the model cancelled', seconds=round(time.time() - turn.started, 1),
                     model=state.provider.model)
            state.persist()
            return web.json_response({**state.public(), 'cancelled': text})
        except Exception as exc:
            state.error = str(exc)
            state.status = 'The agent did not reply'
            log.warning('chat.failed', 'No reply from the agent: ' + str(exc), exc=exc, model=state.provider.model)
        finally:
            stopper.cancel()
            state.turn = None
        state.persist()
    return web.json_response(state.public())


async def chat_cancel(request):
    """Stop waiting for the model. A reply that already arrived stands."""
    state = request.app['state']
    turn = state.turn
    if turn is None:
        raise ValidationError('No request to cancel')
    if state.controller.cancel(turn):
        state.turn_stop.set()
        state.status = 'Cancelling the request…'
    return web.json_response(state.public())


async def configure(request):
    state = request.app['state']
    not_busy(state)
    data = await request.json()
    async with state.lock:
        kind = data.get('kind', 'chatgpt')
        if kind == 'chatgpt':
            state.status = 'Finish signing in in the new browser tab'
            def show_login(url):
                # Only the official sign-in page is handed to the browser tab.
                if url.startswith('https://'):
                    state.login_url = url
            try:
                provider = await asyncio.to_thread(connect_chatgpt, data.get('model') or None, show_login)
            finally:
                state.login_url = None
        else:
            provider = APIProvider(kind, data.get('endpoint') or PROVIDERS[kind][1], data.get('key', ''))
            provider.model = data.get('model', '').strip()
            if not provider.model:
                raise ValidationError('Enter a model')
            provider = LiveProvider(provider)
        await asyncio.to_thread(state.provider.close)
        state.provider = state.controller.provider = provider
        log.info('provider.connected', f'Model connected: {kind}', kind=kind, model=provider.model)
    return web.json_response(state.public())


async def provider_models(request):
    """The models an API provider offers to this key, so the user picks one instead of typing
    its id. The key is used for this one request and not kept."""
    data = await request.json()
    kind = data.get('kind')
    if kind not in PROVIDERS or kind == 'chatgpt':
        raise ValidationError('Pick an API provider')
    provider = APIProvider(kind, data.get('endpoint') or PROVIDERS[kind][1], data.get('key', ''))
    try:
        models = await asyncio.to_thread(provider.models)
    finally:
        provider.close()
    return web.json_response({'models': sorted(set(models))[:500]})


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
        secure_boot = data.get('secure_boot') is True
        config = state.controller.configuration
        state.status = 'Measuring the system and looking for room for the preview…'
        await asyncio.to_thread(state.refresh_inventory)
        consent = consent_binding(config, state.controller.snapshot)
        hardware = state.controller.snapshot['hardware']
        if secure_boot and (state.controller.snapshot['firmware'] != 'uefi' or config.bootloader != 'systemd-boot'):
            raise ValidationError('Signing for Secure Boot needs UEFI boot and the systemd-boot bootloader')
        try:
            await asyncio.to_thread(state.controller.catalog.validate, driver_plan(hardware, config.packages, config.session)['packages'])
        except ValidationError as exc:
            raise ValidationError('An installer problem, not your choice — the drivers for this hardware are missing from the repositories: ' + str(exc))
        estimate = await asyncio.to_thread(state.controller.catalog.estimate, packages_for(config, hardware, secure_boot))
        # A hibernation swap file as large as the real computer's RAM needs that much room on
        # the preview's root, but it is only reserved (never written), so it costs no memory.
        sparse = hibernation_swap_size(hardware.get('memory')) if config.swap == 'hibernate' else 0
        needed = int(estimate['installed'] * 1.2) + 2 * GIB + sparse
        # LUKS output is incompressible: an encrypted in-memory preview needs its full size.
        compression = 1.0 if encrypt else 1.3
        probe = await privileged('storage_worker.py', {'op': 'probe', 'needed': needed, 'target': config.disk, 'sparse': sparse,
                                                       'vm_memory': memory * 2**20, 'compression': compression})
        digest = hashlib.sha256(json.dumps({'consent': consent['digest'], 'needed': needed, 'memory': memory, 'encrypt': encrypt,
                                            'secure_boot': secure_boot,
                                            'options': [o['id'] for o in probe['options']]}, sort_keys=True).encode()).hexdigest()
        state.plan = {'digest': digest, 'estimate': estimate, 'needed': needed, 'sparse': sparse, 'memory': memory, 'encrypt': encrypt,
                      'secure_boot': secure_boot,
                      'compression': compression, 'options': probe['options'], 'consent': consent['digest']}
        log.info('plan.ready', f'Needs {needed / GIB:.1f} GiB, {len(probe["options"])} options', estimate=estimate,
                 needed=needed, options=[{'id': o['id'], 'fits': o['fits']} for o in probe['options']])
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
            raise ValidationError('The configuration, disk, hardware or storage options changed. Find room again')
        option = next((o for o in state.plan['options'] if o['id'] == data.get('option')), None)
        if not option or not option['fits']:
            raise ValidationError('Pick a place for the preview that fits')
        if data.get('accepted') is not True:
            raise ValidationError('Confirm the chosen place')
        if config.login_entries() and data.get('login_reviewed') is not True:
            raise ValidationError('Review and confirm what starts at login')
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
        building = bool(state.build_task and not state.build_task.done())
        if building:
            state.build_task.cancel()
            await asyncio.gather(state.build_task, return_exceptions=True)
        clean = True
        if state.vm:
            if building or not state.vm.running:
                # Cancelling a build stops the installer VM at once; the preview is unfinished anyway.
                await state.vm.stop()
            else:
                # A preview the user keeps is turned off like a computer, never cut off: a power cut
                # leaves its file systems dirty and loses what the guest has not written yet.
                state.status = 'Turning off the preview, as with its power button…'
                clean = await state.vm.shutdown()
                if not clean:
                    log.warning('vm.stop.forced', 'The preview did not turn itself off in time and was stopped')
        if state.disk_ready:
            state.phase, state.status = 'stopped', ('VM turned off. The preview is kept' if clean else
                                                    'The preview did not turn itself off in time and was stopped. The preview is kept')
        if state.record_dirty:
            await state.save_record('Preview VM stopped')
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
    await state.drop_record_task()
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


def found_request(state, data):
    """A found preview of an earlier session, while no other preview or operation is active."""
    entry = state.found_entry(data.get('id'))
    if state.preview or (state.vm and state.vm.running):
        raise ValidationError('Remove the current preview first')
    return entry


async def scan_previews(request):
    state = request.app['state']
    not_busy(state)
    async with state.lock:
        await state.scan()
        return web.json_response(state.public())


async def continue_preview(request):
    """Reattach a completely installed preview from an earlier Live session."""
    state = request.app['state']
    not_busy(state)
    data = await request.json()
    async with state.lock:
        entry = found_request(state, data)
        record = entry.get('record')
        if not record or record['status'] not in ('ready', 'finalizing'):
            raise ValidationError('Installing into this preview did not finish: you can only retry or remove it')
        await asyncio.to_thread(state.rebind, record)  # Refuse before touching the medium.
        adopted = await privileged('storage_worker.py', {'op': 'adopt', 'id': entry['id']})
        record = preview_record.clean(adopted['record'])
        config, consent = await asyncio.to_thread(state.rebind, record)
        storage = record['storage']
        option = {'id': entry['id'], 'kind': storage['kind'], 'title': storage['title'] or entry['medium'],
                  'revert': storage['revert'], 'destructive': False, 'confirm': None}
        state.preview = {'option': option, 'image': adopted['image'], 'revert': adopted['revert'], 'record': record}
        state.built = {'configuration': config.as_dict(), 'consent': consent, 'encrypted': record['encrypted'],
                       'hardware': record['hardware'], 'secure_boot': record['secure_boot']}
        state.disk_ready, state.plan, state.error, state.events = True, None, None, []
        state.final = {'phase': 'idle', 'events': []}
        state.vm = VirtualMachine(adopted['image'], record['vm']['memory'], record['vm']['cpus'], state.controller.snapshot['firmware'])
        state.saved_vm = None
        interrupted = record['status'] == 'finalizing'
        state.restore_conversation(config, 'Continuing the preview from an earlier session: ' + option['title'] + '. '
                                   + ('Installing on the computer’s disk was interrupted back then — its success is not confirmed. ' if interrupted else '')
                                   + 'Start the preview again or install the system on this computer.')
        state.phase, state.status = 'stopped', 'Preview from an earlier session reattached'
        state.found = [e for e in state.found if e['id'] != entry['id']]
        await state.save_record('Preview continued after a Live restart', status='ready')
        state.persist()
        return web.json_response(state.public())


async def retry_preview(request):
    """An unfinished installation: undo its storage and return its configuration to the review."""
    state = request.app['state']
    not_busy(state)
    data = await request.json()
    async with state.lock:
        entry = found_request(state, data)
        record = entry.get('record')
        if not record or record['status'] not in ('installing', 'failed'):
            raise ValidationError('Only an unfinished installation can be retried')
        config, _ = await asyncio.to_thread(state.rebind, record)
        result = await privileged('storage_worker.py', {'op': 'remove', 'id': entry['id']})
        state.plan, state.error = None, None
        state.restore_conversation(config, 'Installing into the preview from an earlier session did not finish. Its temporary storage is removed ('
                                   + result['text'] + '). The configuration is restored: find room and build the preview again.')
        state.status = 'Configuration restored: pick where the preview lives'
        await state.scan()
        state.persist()
        return web.json_response(state.public())


async def remove_found(request):
    """Undo a preview left by an earlier session; other partitions and files stay untouched."""
    state = request.app['state']
    not_busy(state)
    data = await request.json()
    async with state.lock:
        entry = state.found_entry(data.get('id'))
        current = state.preview and (state.preview['image']['path'], state.preview['revert'].get('device'))
        if current and entry['device'] in current:
            raise ValidationError('This is the current preview: remove it with “Put everything back”')
        result = await privileged('storage_worker.py', {'op': 'remove', 'id': entry['id']})
        await asyncio.to_thread(state.refresh_inventory)
        await state.scan()
        state.status = result['text']
        return web.json_response(state.public())


def discard_preview_logs():
    """Remove the preview VMs' directories: QEMU and guest console logs, UEFI variables,
    sockets. Only after a successful finalization: on failure they are the diagnostics."""
    removed = 0
    for directory in (DATA_ROOT / 'vm').glob('web-*'):
        if directory.is_dir() and not directory.is_symlink():
            shutil.rmtree(directory, ignore_errors=True)
            removed += not directory.exists()
    return removed


async def finalize_task(state, payload):
    state.final = {'phase': 'working', 'target': payload['target'], 'layout': payload['layout'], 'events': []}
    state.persist()
    current_operation.set(new_operation('finalize'))
    log.info('finalize.start', f'Finishing the installation on {payload["target"]}: {payload["layout"]}',
             target=payload['target'], layout=payload['layout'], encrypted=bool(payload.get('passphrase')))
    stderr = ''
    await state.save_record('Started installing on the disk ' + payload['target'], status='finalizing')
    try:
        process = await asyncio.create_subprocess_exec(
            'sudo', '-n', '/usr/bin/python', '-B', str(ROOT / 'web/finalize_worker.py'),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        process.stdin.write(json.dumps(traced(payload)).encode() + b'\n')
        await process.stdin.drain()
        process.stdin.close()
        payload.pop('passphrase', None)
        stderr_task = asyncio.create_task(process.stderr.read())
        complete, mode = False, None
        async for line in process.stdout:
            event = json.loads(line)
            events = state.final['events']
            if event.get('step') and events and events[-1].get('step') == event['step']:
                events[-1] = event  # A step's next percentage replaces its previous one.
            else:
                events.append(event)
            state.status = event.get('text', state.status)
            if event.get('percent') is None or event['percent'] % 25 == 0:
                log.log('error' if event.get('kind') == 'final-error' else 'warning' if event.get('kind') == 'final-warning' else 'info',
                        'finalize.event.' + str(event.get('kind')), str(event.get('text', '')))
            if event['kind'] == 'final-warning':
                state.final.setdefault('warnings', []).append(event['text'])
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
        # The preview is finished for good: its logs and firmware state are not needed any more.
        state.vm = state.saved_vm = None
        if await asyncio.to_thread(discard_preview_logs):
            state.final['events'].append({'kind': 'final-progress', 'text': 'Preview logs and working files deleted'})
        state.phase, state.status = 'finalized', 'Ready to boot from this computer’s disk'
        log.info('finalize.done', 'System installed on the computer’s disk', mode=mode)
    except Exception as exc:
        state.final.update(phase='error', error=str(exc))
        state.status = 'Installing to disk did not finish'
        log.error('finalize.failed', str(exc), exc=exc, stderr=stderr[-1500:])
        if state.preview:
            await state.save_record('Installing to disk did not finish', status='ready', error=str(exc))
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
        enroll = data.get('enroll_keys') is True
        if enroll and not built.get('secure_boot'):
            raise ValidationError('The system in the preview is not signed for Secure Boot')
        if enroll and profile(state.controller.snapshot['hardware'])['setup_mode'] is not True:
            raise ValidationError('The firmware is not in Setup Mode: Secure Boot keys can’t be enrolled now')
        payload = {'target': built['consent']['target'], 'fingerprint': built['consent']['fingerprint'],
                   'configuration': built['configuration'], 'passphrase': passphrase,
                   'image': state.preview['image'], 'layout': layout, 'confirmation': data['confirmation'],
                   'enroll_keys': enroll}
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
    log.info('power.' + action, 'Scheduled: ' + action)
    proc = await asyncio.create_subprocess_exec('sudo', '-n', '/usr/bin/shutdown', '-h' if action == 'poweroff' else '-r', '+1')
    if await proc.wait():
        raise ValidationError('Could not schedule the power action')
    message = ('Live powers off in a minute. Remove the stick and power on the computer: it boots from the installed disk.'
               if action == 'poweroff' else 'The computer restarts in a minute. Remove the AGIOS stick so the installed system boots.')
    return web.json_response({'scheduled': True, 'message': message})


async def export_diagnostics(request):
    """A secret-free archive of logs, state, inventory and versions for a bug report."""
    state = request.app['state']
    public = {k: v for k, v in state.public().items() if k != 'messages'}
    data = await asyncio.to_thread(diagnostics.bundle, public, state.controller.snapshot, DATA_ROOT, ROOT)
    name = 'agios-diagnostics-' + time.strftime('%Y%m%d-%H%M%S') + '.tar.gz'
    log.info('diagnostics.exported', f'Diagnostics saved: {name}', size=len(data))
    return web.Response(body=data, content_type='application/gzip',
                        headers={'Content-Disposition': f'attachment; filename="{name}"', 'Cache-Control': 'no-store'})


async def startup(app):
    state = app['state']
    if live_environment():
        state.scan_task = asyncio.create_task(state.scan())


async def cleanup(app):
    state = app['state']
    if state.scan_task and not state.scan_task.done():
        state.scan_task.cancel()
    if state.final_task and not state.final_task.done():
        await asyncio.shield(state.final_task)
    building = bool(state.build_task and not state.build_task.done())
    if building:
        state.build_task.cancel()
        await asyncio.gather(state.build_task, return_exceptions=True)
    if state.vm:
        if building:
            await state.vm.stop()
        else:
            # The Live is shutting down: give a kept preview a short chance to turn itself off.
            await state.vm.shutdown(timeout=30)
    await asyncio.to_thread(state.provider.close)


def application(port=8787, guacd_port=14822):
    app = web.Application(middlewares=[local_only], client_max_size=1_000_000)
    app['state'] = State(guacd_port)
    app['hosts'] = {f'localhost:{port}', f'127.0.0.1:{port}'}
    app.router.add_get('/api/state', state_get)
    app.router.add_post('/api/chat', chat)
    app.router.add_post('/api/chat/cancel', chat_cancel)
    app.router.add_post('/api/provider', configure)
    app.router.add_post('/api/provider/models', provider_models)
    app.router.add_post('/api/plan', plan)
    app.router.add_post('/api/build', build)
    app.router.add_post('/api/stop', stop)
    app.router.add_post('/api/resume', resume)
    app.router.add_post('/api/revert', revert)
    app.router.add_post('/api/previews/scan', scan_previews)
    app.router.add_post('/api/previews/continue', continue_preview)
    app.router.add_post('/api/previews/retry', retry_preview)
    app.router.add_post('/api/previews/remove', remove_found)
    app.router.add_post('/api/final/finalize', finalize)
    app.router.add_post('/api/final/power', power)
    app.router.add_post('/api/diagnostics', export_diagnostics)
    app.router.add_get('/api/version', version_get)
    app.router.add_post('/api/version/check', version_check)
    app.router.add_get('/tunnel', tunnel)
    app.router.add_get('/', index)
    app.router.add_static('/static', ROOT / 'web/static')
    if FONTS.is_dir():
        app.router.add_static('/fonts', FONTS)
    app.router.add_get('/guacamole.js', guacamole_script)
    app.on_startup.append(startup)
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
    log.info('site.start', 'AGIOS website started', port=args.port,
             revision=((ROOT / 'source-revision').read_text().strip() if (ROOT / 'source-revision').exists() else None))
    web.run_app(application(args.port, args.guacd_port), host='127.0.0.1', port=args.port, access_log=None, shutdown_timeout=5)
