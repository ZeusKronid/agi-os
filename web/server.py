#!/usr/bin/env python3
"""Local AGIOS website: conversation, VM installation and Guacamole preview."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

vendor = Path(__file__).resolve().parent / 'vendor'
if vendor.is_dir():
    sys.path.insert(0, str(vendor))
from aiohttp import web

from settings import SOURCE_ROOT as ROOT, ENGINE, DATA_ROOT, INSTALLER_ISO, GUACAMOLE_JS
sys.path.insert(0, str(ENGINE))
from controller import Controller
from domain import Configuration, ValidationError
from providers import APIProvider, ProviderError, PROVIDERS
from system import demo_inventory
from runtime import VirtualMachine
from guacamole import tunnel

from provider import LiveProvider, connect_chatgpt
from system import live_environment
from deployment import review as deployment_review, target_inventory


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
        self.deploy_task = None
        self.final_review = None
        self.lock = asyncio.Lock()
        self.provider = LiveProvider()
        snapshot = demo_inventory()
        snapshot['disks'][0].update(model='Новый виртуальный диск AGIOS', serial='', size=32 * 2**30)
        self.controller = Controller(snapshot, self.provider, notify=self.notify)
        self.record = DATA_ROOT / 'session.json'
        self.restore()

    def notify(self, kind, value):
        if kind == 'status':
            self.status = value

    def persist(self):
        self.record.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = {'messages': self.messages, 'history': self.controller.history,
                'configuration': self.controller.configuration.as_dict() if self.controller.configuration else None,
                'vm': str(self.vm.directory) if self.vm else self.saved_vm,
                'disk_ready': self.phase == 'ready' or getattr(self, 'disk_ready', False),
                'built_digest': self.built_digest, 'deployment': self.deployment}
        temp = self.record.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False))
        temp.chmod(0o600)
        temp.replace(self.record)

    def restore(self):
        self.built_digest = None
        self.deployment = {'phase': 'idle', 'events': []}
        self.saved_vm = None
        self.disk_ready = False
        if self.record.exists():
            data = json.loads(self.record.read_text())
            self.messages = data['messages']
            self.controller.history = data['history']
            if data.get('configuration'):
                self.controller.configuration = Configuration.parse(data['configuration'])
            self.saved_vm = data.get('vm')
            self.disk_ready = data.get('disk_ready', False)
            self.built_digest = data.get('built_digest')
            self.deployment = data.get('deployment', {'phase':'idle','events':[]})
            if self.deployment['phase'] == 'writing':
                self.deployment.update(phase='error', error='Перенос прерван. Конечный диск требует проверки; успех не подтверждён.')

    def public(self):
        config = self.controller.configuration
        return {'messages': self.messages, 'status': self.status, 'phase': self.phase,
                'error': self.error, 'model': self.provider.model,
                'configuration': config.as_dict() if config else None,
                'summary': config.summary(self.controller.snapshot['disks'][0]) if config else None,
                'digest': config.digest() if config else None,
                'events': self.events[-100:], 'running': bool(self.vm and self.vm.running),
                'console_id': self.vm.process.pid if self.vm and self.vm.running else None,
                'vm': str(self.vm.directory) if self.vm else self.saved_vm,
                'can_resume': self.disk_ready and not (self.vm and self.vm.running),
                'built_digest': self.built_digest, 'deployment': self.deployment,
                'final_review': self.final_review,
                'can_deploy': bool(self.disk_ready and config and self.built_digest == config.digest())}

    async def build(self, config, password, memory, cpus):
        try:
            self.phase, self.status = 'starting', 'Запускаю установочную VM'
            self.disk_ready = False
            self.built_digest = None
            self.final_review = None
            self.deployment = {'phase': 'idle', 'events': []}
            self.vm = VirtualMachine(memory, cpus)
            self.persist()
            await self.vm.start()
            self.phase, self.status = 'installing', 'Ожидаю готовности установщика внутри VM'
            def event(value):
                self.events.append(value)
                self.status = value.get('text', self.status)
            await self.vm.install(config, password, event)
            self.phase, self.status = 'ready', 'Система установлена. VM загружается с диска без ISO'
            self.disk_ready = True
            self.built_digest = config.digest()
        except asyncio.CancelledError:
            self.phase, self.status = 'stopped', 'VM остановлена. Виртуальный диск сохранён'
            raise
        except Exception as exc:
            self.phase, self.error, self.status = 'error', str(exc) or 'Превышено время ожидания VM', 'Сборка не завершена'
        finally:
            password = None
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


async def chat(request):
    state = request.app['state']
    if state.lock.locked() or state.controller.installing:
        raise web.HTTPConflict(text='Дождитесь завершения текущей операции')
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
            reply = await asyncio.to_thread(state.controller.respond, text)
            state.messages.append({'role': 'assistant', 'content': reply['message'], 'suggestions': reply['suggestions']})
            state.status = 'Конфигурация готова к сборке' if state.controller.configuration else 'Продолжим обсуждение'
        except Exception as exc:
            state.error = str(exc)
            state.status = 'Не удалось получить ответ агента'
        state.persist()
    return web.json_response(state.public())


async def configure(request):
    state = request.app['state']
    if state.lock.locked() or state.controller.installing:
        raise web.HTTPConflict(text='Сейчас выполняется операция')
    data = await request.json()
    async with state.lock:
        if state.controller.installing:
            raise web.HTTPConflict(text='Дождитесь завершения установки')
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


async def build(request):
    state = request.app['state']
    if state.lock.locked() or state.controller.installing or (state.vm and state.vm.running):
        raise web.HTTPConflict(text='Остановите текущую VM перед новой сборкой')
    data = await request.json()
    if state.lock.locked() or state.controller.installing or (state.vm and state.vm.running):
        raise web.HTTPConflict(text='Дождитесь завершения текущей операции')
    config = state.controller.configuration
    if not config or data.get('digest') != config.digest():
        raise ValidationError('Конфигурация изменилась. Проверьте её ещё раз')
    password = data.get('password', '')
    if not isinstance(password, str) or not 8 <= len(password) <= 256 or any(c in password for c in '\n\r\0'):
        raise ValidationError('Пароль должен содержать от 8 до 256 символов без переносов строк')
    memory, cpus = data.get('memory', 4096), data.get('cpus', 4)
    if type(memory) is not int or not 2048 <= memory <= 32768 or type(cpus) is not int or not 1 <= cpus <= 16:
        raise ValidationError('Допустимо 2–32 ГиБ RAM и 1–16 CPU')
    if not INSTALLER_ISO.exists():
        raise ValidationError('В Live ISO отсутствует образ установщика внутренней VM')
    state.error = None
    state.events = []
    state.controller.installing = True
    state.build_task = asyncio.create_task(state.build(config, password, memory, cpus))
    return web.json_response({'accepted': True}, status=202)


async def stop(request):
    state = request.app['state']
    if state.lock.locked() or state.deployment['phase'] == 'writing':
        raise web.HTTPConflict(text='Дождитесь завершения текущей операции')
    async with state.lock:
        if state.build_task and not state.build_task.done():
            state.build_task.cancel()
            await asyncio.gather(state.build_task, return_exceptions=True)
        if state.vm:
            await state.vm.stop()
        state.phase, state.status = 'stopped', 'VM остановлена. Диск сохранён'
        state.persist()
        return web.json_response(state.public())

async def resume(request):
    state = request.app['state']
    if state.lock.locked() or state.deployment['phase'] == 'writing':
        raise web.HTTPConflict(text='Дождитесь завершения текущей операции')
    async with state.lock:
        if state.controller.installing or (state.vm and state.vm.running) or not state.disk_ready:
            raise ValidationError('Нет остановленной установленной системы')
        if not state.vm:
            # Restore only a generated VM directory inside this project.
            directory = Path(state.saved_vm).resolve()
            if directory.parent != (DATA_ROOT / 'vm').resolve() or not directory.name.startswith('web-'):
                raise ValidationError('Некорректный путь VM')
            vm = VirtualMachine.__new__(VirtualMachine)
            from runtime import available_port
            vm.directory, vm.memory, vm.cpus, vm.disk_gib = directory, 4096, 4, 32
            vm.vnc_port = available_port()
            vm.process = vm.log = vm.server = vm.connection = vm.reader = vm.writer = None
            state.vm = vm
        await state.vm.start(install=False)
        state.phase, state.status = 'ready', 'VM запущена с сохранённого виртуального диска'
        return web.json_response(state.public())

def deployable(state):
    config = state.controller.configuration
    if state.controller.installing or state.deployment['phase'] == 'writing':
        raise ValidationError('Дождитесь завершения текущей установки')
    if not state.disk_ready or not config or state.built_digest != config.digest():
        raise ValidationError('Сначала соберите и проверьте актуальную конфигурацию в превью')
    if state.vm and state.vm.running:
        raise ValidationError('Сначала завершите работу системы внутри превью через меню выключения')
    directory = Path(state.vm.directory if state.vm else state.saved_vm).resolve()
    if directory.parent != (DATA_ROOT / 'vm').resolve() or not directory.name.startswith('web-'):
        raise ValidationError('Некорректный путь превью')
    return directory / 'system.qcow2', config


async def targets(request):
    snapshot = await asyncio.to_thread(target_inventory)
    return web.json_response(snapshot)


async def final_review(request):
    state = request.app['state']
    data = await request.json()
    async with state.lock:
        image, config = deployable(state)
        state.final_review = await asyncio.to_thread(deployment_review, image, config, data['target'])
        return web.json_response(state.public())


async def transfer_task(state, proposal, confirmation):
    state.controller.installing = True
    state.deployment = {'phase':'writing', 'target':proposal['target'], 'events':[]}
    state.persist()
    try:
        payload = {k:proposal[k] for k in ('source','identity','configuration','target','digest')}
        payload['confirmation'] = confirmation
        process = await asyncio.create_subprocess_exec(
            'sudo', '-n', '/usr/bin/python', '-B', str(ROOT / 'web/deploy_worker.py'),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        process.stdin.write(json.dumps(payload).encode()+b'\n')
        await process.stdin.drain()
        process.stdin.close()
        stderr_task = asyncio.create_task(process.stderr.read())
        complete = False
        async for line in process.stdout:
            event = json.loads(line)
            state.deployment['events'].append(event)
            state.status = event.get('text', state.status)
            if event['kind'] == 'deployed':
                complete = True
            if event['kind'] == 'deploy-error':
                state.deployment['error'] = event['text']
        code = await process.wait()
        stderr = (await stderr_task).decode(errors='replace')
        if code or not complete:
            raise ValidationError(state.deployment.get('error') or stderr[-1500:] or 'Перенос не завершён')
        state.deployment['phase'] = 'complete'
    except Exception as exc:
        state.deployment.update(phase='error', error=str(exc))
        state.status = 'Установка на конечный диск не завершена'
    finally:
        state.controller.installing = False
        state.final_review = None
        state.persist()


async def final_install(request):
    state = request.app['state']
    data = await request.json()
    async with state.lock:
        image, config = deployable(state)
        proposal = state.final_review
        if not proposal or data.get('digest') != proposal['digest']:
            raise ValidationError('Проверьте конечный диск заново')
        if data.get('confirmation') != proposal['target'] or data.get('preview_accepted') is not True:
            raise ValidationError('Подтвердите проверку превью и введите путь выбранного диска')
        current = await asyncio.to_thread(deployment_review, image, config, proposal['target'])
        if current['digest'] != proposal['digest']:
            state.final_review = None
            raise ValidationError('Образ или конечный диск изменился; нужно новое подтверждение')
        # Mark synchronously before scheduling, preventing a concurrent second submission.
        state.controller.installing = True
        state.deployment = {'phase':'writing','target':proposal['target'],'events':[]}
        state.deploy_task = asyncio.create_task(transfer_task(state, proposal, data['confirmation']))
        return web.json_response({'accepted':True}, status=202)


async def finish_live(request):
    state = request.app['state']
    if state.deployment['phase'] != 'complete' or state.controller.installing:
        raise ValidationError('Сначала завершите установку на конечный диск')
    if not live_environment():
        raise ValidationError('Выключение доступно только внутри Live')
    proc = await asyncio.create_subprocess_exec('sudo', '-n', 'shutdown', '-h', '+1')
    if await proc.wait():
        raise ValidationError('Не удалось запланировать выключение')
    return web.json_response({'scheduled':True, 'message':'Live выключится через минуту. После выключения извлеките носитель и загрузитесь с конечного диска.'})


async def cleanup(app):
    state = app['state']
    if state.deploy_task and not state.deploy_task.done():
        await asyncio.shield(state.deploy_task)
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
    app.router.add_post('/api/build', build)
    app.router.add_post('/api/stop', stop)
    app.router.add_post('/api/resume', resume)
    app.router.add_get('/api/targets', targets)
    app.router.add_post('/api/final/review', final_review)
    app.router.add_post('/api/final/install', final_install)
    app.router.add_post('/api/final/poweroff', finish_live)
    app.router.add_get('/tunnel', tunnel)
    app.router.add_get('/', index)
    app.router.add_static('/static', ROOT / 'web/static')
    app.router.add_get('/guacamole.js', guacamole_script)
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
    web.run_app(application(args.port, args.guacd_port), host='127.0.0.1', port=args.port, access_log=None)
