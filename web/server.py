#!/usr/bin/env python3
"""Local AGIOS website: conversation, reversible preview, installation onto the computer's disk."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from aiohttp import web

from settings import SOURCE_ROOT as ROOT, ENGINE, DATA_ROOT, GUACAMOLE_JS
sys.path.insert(0, str(ENGINE))
from controller import Controller
from domain import Configuration, ValidationError
from providers import APIProvider, ProviderError, PROVIDERS
from worker import packages_for
from hardware import describe, driver_plan, profile, virtual
from runtime import VirtualMachine
from guacamole import tunnel

from provider import LiveProvider, connect_chatgpt
from system import live_environment
from deployment import consent as consent_binding, target_inventory
import preview_record

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
        raise ValidationError('Операция с носителем не выполнена: ' + err.decode(errors='replace')[-800:])
    return answer['result']


class State:
    def __init__(self, guacd_port):
        self.guacd_port = guacd_port
        self.messages = []
        self.events = []
        self.status = 'Опишите систему, которую хотите собрать'
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
                warning = 'Запись превью не сохранена в хранилище: ' + str(exc) + '. После перезапуска Live продолжить это превью не получится.'
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
            self.found, self.scan_error = [], 'Поиск превью прошлых сеансов не выполнен: ' + str(exc)

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
                item['title'] = f"{config['hostname']} · {config['desktop']} · пользователь {config['username']}"
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
            raise ValidationError('Такого превью нет; обновите список')
        return entry

    def rebind(self, record):
        """The record's configuration bound to this computer's current view of its target disk."""
        snapshot = self.refresh_inventory()
        if record['firmware'] != snapshot['firmware']:
            raise ValidationError('Превью установлено для загрузки ' + record['firmware'].upper()
                                  + ', а Live сейчас загружен в режиме ' + snapshot['firmware'].upper())
        matches = [d for d in snapshot['disks'] if preview_record.same_disk(record['target'], d)]
        if len(matches) > 1:
            matches = [d for d in matches if d['path'] == record['target']['path']]
        if len(matches) != 1:
            raise ValidationError('Целевой диск этого превью (' + record['target']['path'] + ') не найден')
        config = Configuration.parse({**record['configuration'], 'disk': matches[0]['path']})
        return config, consent_binding(config, snapshot)

    def restore_conversation(self, config, text):
        """Give the agreed configuration back to the conversation (and to the model's context)."""
        reply = {'message': text, 'suggestions': [], 'lookup': [], 'configuration': config.as_dict()}
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
                self.controller.configuration = Configuration.parse(data['configuration'])
            self.saved_vm = data.get('vm')
            self.disk_ready = data.get('disk_ready', False)
            self.built = data.get('built')
            self.preview = data.get('preview')
            self.final = data.get('final', {'phase': 'idle', 'events': []})
            if self.final['phase'] == 'working':
                self.final.update(phase='error', error='Завершение установки прервано. Проверьте диск; успех не подтверждён.')
            if self.final['phase'] == 'complete':
                self.phase, self.status = 'finalized', 'Система готова к загрузке с диска компьютера'
            elif self.preview and self.preview.get('revert', {}).get('kind') == 'ram' and not Path(self.preview['image']['path']).exists():
                # Memory does not survive a Live restart: the preview is gone, the disks were never touched.
                self.preview, self.built, self.disk_ready, self.saved_vm = None, None, False, None
            elif self.preview and not self.disk_ready:
                # The site stopped during the installation into the preview: never a silent success.
                self.phase = 'error'
                self.status = 'Установка в превью не завершена'
                self.error = 'Установка в превью была прервана. Уберите превью и соберите его заново.'

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
            built = {'summary': built_config.summary(self.built['consent']['disk'], self.built.get('hardware')), 'target': self.built['consent']['target'],
                     'encrypted': self.built['encrypted'], 'digest': self.built['consent']['digest'],
                     'storage': self.preview['option']['title'] if self.preview else None,
                     'on_target': bool(self.preview and self.preview['image']['format'] == 'raw'
                                       and self.preview['image']['path'].startswith(self.built['consent']['target'])),
                     'revert': self.preview['option']['revert'] if self.preview else None}
        return {'messages': self.messages, 'status': self.status, 'phase': self.phase,
                'error': self.error, 'model': self.provider.model,
                'firmware': snapshot['firmware'], 'found': self.found_public(),
                'scanning': bool(self.scan_task and not self.scan_task.done()), 'scan_error': self.scan_error,
                'disks': [{k: d.get(k) for k in ('path', 'size', 'model', 'serial', 'eligible', 'reason', 'partitions')} for d in snapshot['disks']],
                'configuration': config.as_dict() if config else None,
                'summary': config.summary(consent['disk'], snapshot['hardware']) if config and consent and 'disk' in consent else None,
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
                self.error = 'Оперативной памяти не хватило для превью; установка остановлена. Выберите другое хранилище.'
                await self.vm.stop()
                return
            await asyncio.sleep(2)

    async def build(self, config, consent, option, password, passphrase, memory, cpus):
        watchdog = None
        try:
            self.phase, self.status = 'starting', 'Готовлю хранилище превью: ' + option['title']
            self.disk_ready = False
            self.built = None
            self.final = {'phase': 'idle', 'events': []}
            self.persist()
            prepared = await privileged('storage_worker.py', {'op': 'prepare', 'option': option, 'needed': self.plan['needed'],
                                                              'vm_memory': memory * 2**20, 'target': config.disk,
                                                              'compression': self.plan['compression']})
            hardware = profile(self.controller.snapshot['hardware'])
            self.preview = {'option': option, **prepared,
                            'record': self.new_record(config, consent, option, prepared, bool(passphrase), hardware, memory, cpus)}
            self.vm = VirtualMachine(prepared['image'], memory, cpus)
            self.persist()
            await self.save_record('Хранилище превью подготовлено: ' + option['title'])
            self.status = 'Запускаю установочную VM'
            await self.vm.start()
            if prepared.get('monitor'):
                watchdog = asyncio.create_task(self.monitor_memory())
            self.phase, self.status = 'installing', 'Ожидаю готовности установщика внутри VM'
            stages = set()
            def event(value):
                self.events.append(value)
                self.status = value.get('text', self.status)
                if value.get('stage') not in stages and value.get('text'):
                    stages.add(value.get('stage'))
                    self.journal_later(value['text'])
            await self.vm.install(config, password, passphrase, event, hardware)
            self.phase, self.status = 'ready', 'Система установлена в превью и загружена'
            self.disk_ready = True
            self.built = {'configuration': config.as_dict(), 'consent': consent, 'encrypted': bool(passphrase), 'hardware': hardware}
            await self.save_record('Система установлена в превью', status='ready')
        except asyncio.CancelledError:
            self.phase, self.status = 'stopped', 'VM остановлена. Установка не завершена'
            self.journal('Установка в превью остановлена', status='failed', error=self.status)
            raise
        except Exception as exc:
            self.phase, self.status = 'error', 'Установка не завершена'
            self.error = self.error or str(exc) or 'Превышено время ожидания VM'
            await self.save_record('Установка в превью не завершена', status='failed', error=self.error)
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
        return web.json_response({'error': str(exc)}, status=400)


async def index(request):
    return web.FileResponse(ROOT / 'web/static/index.html')


async def guacamole_script(request):
    return web.FileResponse(GUACAMOLE_JS)


async def state_get(request):
    return web.json_response(request.app['state'].public())


def not_busy(state):
    if state.lock.locked() or state.controller.installing or state.final['phase'] == 'working':
        raise web.HTTPConflict(text='Дождитесь завершения текущей операции')


async def chat(request):
    state = request.app['state']
    not_busy(state)
    data = await request.json()
    text = data.get('text', '')
    if not isinstance(text, str) or not text.strip() or len(text) > 16000:
        raise ValidationError('Введите сообщение длиной до 16000 символов')
    async with state.lock:
        if state.controller.installing:
            raise web.HTTPConflict(text='Дождитесь завершения установки')
        state.error = None
        state.messages.append({'role': 'user', 'content': text})
        state.status = 'Агент обдумывает конфигурацию…'
        try:
            await asyncio.to_thread(state.refresh_inventory)
            reply = await asyncio.to_thread(state.controller.respond, text)
            state.messages.append({'role': 'assistant', 'content': reply['message'], 'suggestions': reply['suggestions']})
            state.status = 'Конфигурация готова: выберите, где сделать превью' if state.controller.configuration else 'Продолжим обсуждение'
            state.plan = None
        except Exception as exc:
            state.error = str(exc)
            state.status = 'Не удалось получить ответ агента'
        state.persist()
    return web.json_response(state.public())


async def configure(request):
    state = request.app['state']
    not_busy(state)
    data = await request.json()
    async with state.lock:
        kind = data.get('kind', 'chatgpt')
        if kind == 'chatgpt':
            state.status = 'Завершите вход в открывшейся вкладке браузера'
            provider = await asyncio.to_thread(connect_chatgpt, data.get('model') or None)
        else:
            provider = APIProvider(kind, data.get('endpoint') or PROVIDERS[kind][1], data.get('key', ''))
            provider.model = data.get('model', '').strip()
            if not provider.model:
                raise ValidationError('Укажите модель')
            provider = LiveProvider(provider)
        await asyncio.to_thread(state.provider.close)
        state.provider = state.controller.provider = provider
    return web.json_response(state.public())


def vm_size(data):
    memory, cpus = data.get('memory', 4096), data.get('cpus', 4)
    if type(memory) is not int or not 2048 <= memory <= 32768 or type(cpus) is not int or not 1 <= cpus <= 16:
        raise ValidationError('Допустимо 2–32 ГиБ RAM и 1–16 CPU')
    return memory, cpus


async def plan(request):
    """Estimate the system size and list reversible places for the preview."""
    state = request.app['state']
    not_busy(state)
    data = await request.json()
    async with state.lock:
        if not state.public()['can_plan']:
            raise ValidationError('Сначала согласуйте конфигурацию с агентом или уберите текущее превью')
        memory, _ = vm_size(data)
        encrypt = data.get('encrypt') is True
        config = state.controller.configuration
        state.status = 'Считаю размер системы и ищу место для превью…'
        await asyncio.to_thread(state.refresh_inventory)
        consent = consent_binding(config, state.controller.snapshot)
        hardware = state.controller.snapshot['hardware']
        try:
            await asyncio.to_thread(state.controller.catalog.validate, driver_plan(hardware, config.packages, config.session)['packages'])
        except ValidationError as exc:
            raise ValidationError('Ошибка установщика, не вашего выбора — драйверы по железу отсутствуют в репозиториях: ' + str(exc))
        estimate = await asyncio.to_thread(state.controller.catalog.estimate, packages_for(config, hardware))
        needed = int(estimate['installed'] * 1.2) + 2 * GIB
        # LUKS output is incompressible: an encrypted in-memory preview needs its full size.
        compression = 1.0 if encrypt else 1.3
        probe = await privileged('storage_worker.py', {'op': 'probe', 'needed': needed, 'target': config.disk,
                                                       'vm_memory': memory * 2**20, 'compression': compression})
        digest = hashlib.sha256(json.dumps({'consent': consent['digest'], 'needed': needed, 'memory': memory, 'encrypt': encrypt,
                                            'options': [o['id'] for o in probe['options']]}, sort_keys=True).encode()).hexdigest()
        state.plan = {'digest': digest, 'estimate': estimate, 'needed': needed, 'memory': memory, 'encrypt': encrypt,
                      'compression': compression, 'options': probe['options'], 'consent': consent['digest']}
        state.status = 'Выберите, где сделать превью, и подтвердите'
        return web.json_response(state.public())


def secret_text(value, name, low, high):
    if not isinstance(value, str) or not low <= len(value) <= high or any(c in value for c in '\n\r\0'):
        raise ValidationError(f'{name}: от {low} до {high} символов без переносов строк')
    return value


async def build(request):
    state = request.app['state']
    not_busy(state)
    if state.vm and state.vm.running:
        raise web.HTTPConflict(text='Остановите текущую VM перед новой установкой')
    data = await request.json()
    async with state.lock:
        if state.controller.installing or (state.vm and state.vm.running) or state.preview:
            raise web.HTTPConflict(text='Сначала уберите текущее превью')
        config = state.controller.configuration
        if not config or not state.plan:
            raise ValidationError('Сначала рассчитайте место для превью')
        await asyncio.to_thread(state.refresh_inventory)
        consent = consent_binding(config, state.controller.snapshot)
        if data.get('digest') != state.plan['digest'] or state.plan['consent'] != consent['digest']:
            raise ValidationError('Конфигурация, диск, оборудование или варианты хранилища изменились. Рассчитайте место заново')
        option = next((o for o in state.plan['options'] if o['id'] == data.get('option')), None)
        if not option or not option['fits']:
            raise ValidationError('Выберите подходящий вариант хранилища превью')
        if data.get('accepted') is not True:
            raise ValidationError('Подтвердите выбранный вариант')
        if option['destructive'] and data.get('confirmation') != option['confirm']:
            raise ValidationError('Для этого варианта введите точный путь: ' + option['confirm'])
        password = secret_text(data.get('password', ''), 'Пароль пользователя', 8, 256)
        passphrase = ''
        if state.plan['encrypt']:
            passphrase = secret_text(data.get('passphrase', ''), 'Пароль шифрования', 8, 512)
        memory, cpus = vm_size(data)
        if memory != state.plan['memory']:
            raise ValidationError('Память VM изменилась; рассчитайте место заново')
        state.error = None
        state.events = []
        state.controller.installing = True
        state.build_task = asyncio.create_task(state.build(config, consent, option, password, passphrase, memory, cpus))
        return web.json_response({'accepted': True}, status=202)


async def stop(request):
    state = request.app['state']
    if state.lock.locked() or state.final['phase'] == 'working':
        raise web.HTTPConflict(text='Дождитесь завершения текущей операции')
    async with state.lock:
        if state.build_task and not state.build_task.done():
            state.build_task.cancel()
            await asyncio.gather(state.build_task, return_exceptions=True)
        if state.vm:
            await state.vm.stop()
        if state.disk_ready:
            state.phase, state.status = 'stopped', 'VM остановлена. Превью сохранено'
        if state.record_dirty:
            await state.save_record('VM превью остановлена')
        state.persist()
        return web.json_response(state.public())


async def resume(request):
    state = request.app['state']
    if state.lock.locked() or state.final['phase'] == 'working':
        raise web.HTTPConflict(text='Дождитесь завершения текущей операции')
    async with state.lock:
        if not state.public()['can_resume']:
            raise ValidationError('Нет остановленного превью')
        if not state.vm:
            state.vm = VirtualMachine.restore(state.saved_vm)
        await state.vm.start(install=False)
        state.phase, state.status = 'ready', 'Превью запущено снова'
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
        raise web.HTTPConflict(text='Дождитесь завершения текущей операции')
    async with state.lock:
        if not state.preview or state.final['phase'] == 'complete':
            raise ValidationError('Нет превью, которое можно убрать')
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
        raise ValidationError('Сначала уберите текущее превью')
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
            raise ValidationError('Установка в это превью не была завершена: его можно только повторить или убрать')
        await asyncio.to_thread(state.rebind, record)  # Refuse before touching the medium.
        adopted = await privileged('storage_worker.py', {'op': 'adopt', 'id': entry['id']})
        record = preview_record.clean(adopted['record'])
        config, consent = await asyncio.to_thread(state.rebind, record)
        storage = record['storage']
        option = {'id': entry['id'], 'kind': storage['kind'], 'title': storage['title'] or entry['medium'],
                  'revert': storage['revert'], 'destructive': False, 'confirm': None}
        state.preview = {'option': option, 'image': adopted['image'], 'revert': adopted['revert'], 'record': record}
        state.built = {'configuration': config.as_dict(), 'consent': consent, 'encrypted': record['encrypted'],
                       'hardware': record['hardware']}
        state.disk_ready, state.plan, state.error, state.events = True, None, None, []
        state.final = {'phase': 'idle', 'events': []}
        state.vm = VirtualMachine(adopted['image'], record['vm']['memory'], record['vm']['cpus'], state.controller.snapshot['firmware'])
        state.saved_vm = None
        interrupted = record['status'] == 'finalizing'
        state.restore_conversation(config, 'Продолжаем превью прошлого сеанса: ' + option['title'] + '. '
                                   + ('Установка на диск компьютера тогда была прервана — её успех не подтверждён. ' if interrupted else '')
                                   + 'Запустите превью снова или установите систему на компьютер.')
        state.phase, state.status = 'stopped', 'Превью прошлого сеанса подключено'
        state.found = [e for e in state.found if e['id'] != entry['id']]
        await state.save_record('Превью продолжено после перезапуска Live', status='ready')
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
            raise ValidationError('Повторить можно только незавершённую установку')
        config, _ = await asyncio.to_thread(state.rebind, record)
        result = await privileged('storage_worker.py', {'op': 'remove', 'id': entry['id']})
        state.plan, state.error = None, None
        state.restore_conversation(config, 'Установка в превью прошлого сеанса не была завершена. Временное хранилище убрано ('
                                   + result['text'] + '). Конфигурация восстановлена: рассчитайте место и соберите превью заново.')
        state.status = 'Конфигурация восстановлена: выберите, где сделать превью'
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
            raise ValidationError('Это текущее превью: уберите его кнопкой «вернуть всё как было»')
        result = await privileged('storage_worker.py', {'op': 'remove', 'id': entry['id']})
        await asyncio.to_thread(state.refresh_inventory)
        await state.scan()
        state.status = result['text']
        return web.json_response(state.public())


async def finalize_task(state, payload):
    state.final = {'phase': 'working', 'target': payload['target'], 'layout': payload['layout'], 'events': []}
    state.persist()
    await state.save_record('Начата установка на диск ' + payload['target'], status='finalizing')
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
            if event['kind'] == 'final-warning':
                state.final.setdefault('warnings', []).append(event['text'])
            if event['kind'] == 'finalized':
                complete, mode = True, event.get('mode')
            if event['kind'] == 'final-error':
                state.final['error'] = event['text']
        code = await process.wait()
        stderr = (await stderr_task).decode(errors='replace')
        if code or not complete:
            raise ValidationError(state.final.get('error') or stderr[-1500:] or 'Завершение не выполнено')
        if mode == 'copy':
            # The copy is verified; the temporary preview storage is no longer needed.
            result = await privileged('storage_worker.py', {'op': 'revert', 'state': state.preview['revert']})
            state.final['events'].append({'kind': 'final-progress', 'text': 'Временное хранилище превью убрано: ' + result['text']})
        state.final['phase'] = 'complete'
        state.phase, state.status = 'finalized', 'Система готова к загрузке с диска компьютера'
    except Exception as exc:
        state.final.update(phase='error', error=str(exc))
        state.status = 'Завершение установки не выполнено'
        if state.preview:
            await state.save_record('Установка на диск не выполнена', status='ready', error=str(exc))
    finally:
        payload.pop('passphrase', None)
        state.controller.installing = False
        state.persist()


async def finalize(request):
    state = request.app['state']
    data = await request.json()
    async with state.lock:
        if not state.public()['can_finalize']:
            raise ValidationError('Сначала установите систему в превью и завершите её работу через меню выключения')
        built = state.built
        layout = data.get('layout')
        if layout not in ('erase', 'alongside'):
            raise ValidationError('Выберите: стереть диск или установить рядом с существующими системами')
        if data.get('confirmation') != built['consent']['target'] or data.get('accepted') is not True:
            raise ValidationError('Подтвердите установку и введите точный путь диска: ' + built['consent']['target'])
        await asyncio.to_thread(state.refresh_inventory)
        current = consent_binding(Configuration.parse(built['configuration']), state.controller.snapshot)
        if current['fingerprint'] != built['consent']['fingerprint']:
            raise ValidationError('Конечный диск изменился после подтверждения')
        passphrase = ''
        if built['encrypted']:
            passphrase = secret_text(data.get('passphrase', ''), 'Пароль шифрования', 8, 512)
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
        raise ValidationError('Сначала завершите установку на диск компьютера')
    if not live_environment():
        raise ValidationError('Выключение доступно только внутри Live')
    action = data.get('action')
    if action not in ('poweroff', 'reboot'):
        raise ValidationError('Неизвестное действие')
    proc = await asyncio.create_subprocess_exec('sudo', '-n', 'shutdown', '-h' if action == 'poweroff' else '-r', '+1')
    if await proc.wait():
        raise ValidationError('Не удалось запланировать выключение')
    message = ('Live выключится через минуту. Извлеките носитель и включите компьютер: он загрузится с установленного диска.'
               if action == 'poweroff' else 'Компьютер перезагрузится через минуту. Извлеките носитель AGIOS, чтобы загрузилась установленная система.')
    return web.json_response({'scheduled': True, 'message': message})


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
    app.router.add_post('/api/previews/scan', scan_previews)
    app.router.add_post('/api/previews/continue', continue_preview)
    app.router.add_post('/api/previews/retry', retry_preview)
    app.router.add_post('/api/previews/remove', remove_found)
    app.router.add_post('/api/final/finalize', finalize)
    app.router.add_post('/api/final/power', power)
    app.router.add_get('/tunnel', tunnel)
    app.router.add_get('/', index)
    app.router.add_static('/static', ROOT / 'web/static')
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
        parser.error('Сайт AGIOS запускается внутри загруженной Live-среды. Для теста загрузите Live ISO в QEMU.')
    os.umask(0o077)
    web.run_app(application(args.port, args.guacd_port), host='127.0.0.1', port=args.port, access_log=None, shutdown_timeout=5)
