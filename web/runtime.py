"""One local QEMU VM per build. Host block devices are never attached."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import time
import uuid

from settings import DATA_ROOT, INSTALLER_ISO
from system import live_environment


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class VirtualMachine:
    def __init__(self, memory=4096, cpus=4, disk_gib=32):
        self.directory = DATA_ROOT / 'vm' / ('web-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
        self.directory.mkdir(parents=True, mode=0o700)
        self.memory, self.cpus, self.disk_gib = memory, cpus, disk_gib
        self.vnc_port = available_port()
        self.process = None
        self.log = None
        self.server = None
        self.connection = None
        self.reader = self.writer = None

    @property
    def running(self):
        return self.process is not None and self.process.returncode is None

    async def start(self, install=True):
        if not live_environment():
            raise RuntimeError('VM создаётся только внутри загруженной Live-среды AGIOS')
        if not Path('/dev/kvm').exists():
            raise RuntimeError('KVM недоступен. В тестовой VM включите вложенную виртуализацию.')
        disk = self.directory / 'system.qcow2'
        if not disk.exists():
            proc = await asyncio.create_subprocess_exec('qemu-img', 'create', '-q', '-f', 'qcow2', str(disk), f'{self.disk_gib}G')
            if await proc.wait():
                raise RuntimeError('Не удалось создать виртуальный диск')
        code = Path('/usr/share/edk2/x64/OVMF_CODE.4m.fd')
        nvram = self.directory / 'OVMF_VARS.fd'
        if not nvram.exists():
            shutil.copyfile(code.with_name('OVMF_VARS.4m.fd'), nvram)
        render = next((p for p in sorted(Path('/dev/dri').glob('renderD*')) if os.access(p, os.R_OK | os.W_OK)), None)
        graphics = (['-display', f'egl-headless,rendernode={render}', '-device', 'virtio-vga-gl']
                    if render and os.environ.get('AGIOS_PREVIEW_GL') == '1' else ['-display', 'none', '-device', 'virtio-vga'])
        args = ['qemu-system-x86_64', '-name', 'AGIOS local preview', '-machine', 'q35',
                '-accel', 'kvm', '-cpu', 'host', '-m', str(self.memory), '-smp', str(self.cpus),
                *graphics, '-vnc', f'127.0.0.1:{self.vnc_port - 5900}',
                '-device', 'qemu-xhci', '-device', 'usb-tablet',
                '-nic', 'user,model=virtio-net-pci',
                '-drive', f'file={disk},format=qcow2,if=none,id=system',
                '-device', f'virtio-blk-pci,drive=system,bootindex={2 if install else 1}',
                '-drive', f'if=pflash,format=raw,readonly=on,file={code}',
                '-drive', f'if=pflash,format=raw,file={nvram}',
                '-qmp', f'unix:{self.directory}/qmp.sock,server=on,wait=off']
        if install:
            iso = INSTALLER_ISO
            if not iso.exists():
                raise RuntimeError('В Live ISO отсутствует образ установочной VM')
            cache = Path('/dev/disk/by-label/AGIOS_CACHE')
            marker = Path('/sys/firmware/qemu_fw_cfg/by_name/opt/org.agi-os.test/raw')
            if marker.exists() and cache.exists():
                # Optional read-only package mirror for network-independent QA.
                args += ['-drive', f'file={cache.resolve()},media=cdrom,readonly=on,if=none,id=testcache',
                         '-device', 'ide-cd,drive=testcache,bus=ide.1',
                         '-fw_cfg', 'name=opt/org.agi-os.test-cache,string=1']
            self.connection = asyncio.get_running_loop().create_future()
            async def connect(reader, writer):
                if self.connection.done():
                    writer.close()
                    return
                self.reader, self.writer = reader, writer
                self.connection.set_result(True)
            path = self.directory / 'install.sock'
            self.server = await asyncio.start_unix_server(connect, path=str(path), limit=1_000_000)
            args += ['-drive', f'file={iso},media=cdrom,readonly=on,if=none,id=installer',
                     '-device', 'ide-cd,drive=installer,bootindex=1',
                     '-device', 'virtio-serial-pci', '-chardev', f'socket,id=install,path={path}',
                     '-device', 'virtserialport,chardev=install,name=org.agi-os.install']
        self.log = (self.directory / 'qemu.log').open('ab')
        self.process = await asyncio.create_subprocess_exec(*args, stdout=self.log, stderr=self.log)
        await asyncio.sleep(.5)
        if not self.running:
            raise RuntimeError('QEMU не запустился: ' + (self.directory / 'qemu.log').read_text()[-1500:])

    async def install(self, config, password, notify):
        await asyncio.wait_for(self.connection, 120)
        ready = json.loads(await asyncio.wait_for(self.reader.readline(), 180))
        if ready.get('kind') != 'ready':
            raise RuntimeError('Установочная VM не готова')
        disk = next(d for d in ready['inventory']['disks'] if d['path'] == '/dev/vda' and d['eligible'])
        request = {'configuration': config.as_dict(), 'consent_digest': config.digest(),
                   'fingerprint': disk['fingerprint'], 'password': password}
        self.writer.write(json.dumps(request).encode() + b'\n')
        await self.writer.drain()
        del request, password
        installed = False
        while line := await asyncio.wait_for(self.reader.readline(), 1900):
            event = json.loads(line)
            notify(event)
            if event.get('kind') == 'error':
                raise RuntimeError(event.get('text', 'Установка завершилась ошибкой'))
            installed |= event.get('kind') == 'installed'
            if event.get('kind') == 'shutdown':
                break
        if not installed:
            raise RuntimeError('Связь с установщиком потеряна до завершения установки')
        await asyncio.wait_for(self.process.wait(), 90)
        await self.close_channel()
        self.log.close()
        await self.start(install=False)

    async def close_channel(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except OSError:
                pass
            self.writer = None
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    async def stop(self):
        # Process termination is also the explicit cancel operation for this local MVP.
        if self.running:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 15)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        await self.close_channel()
        if self.log:
            self.log.close()
