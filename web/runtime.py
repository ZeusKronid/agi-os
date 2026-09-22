"""One local QEMU VM per installation, backed by the prepared preview storage.

The inner VM boots the very Live medium this site runs from (kernel, initramfs
and the read-only boot device), installs the agreed system into the preview
image (a file in memory or on a medium, or a temporary partition), then restarts
from that image as the preview. Physical disks are never attached directly.
"""
import asyncio
import json
from pathlib import Path
import shutil
import socket
import time
import uuid

from settings import DATA_ROOT
from system import live_environment, read_command

OVMF = Path('/usr/share/edk2/x64')
BOOTMNT = Path('/run/archiso/bootmnt')
GUEST_OPTIONS = 'agios.guest systemd.unit=multi-user.target'


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def live_firmware():
    return 'uefi' if Path('/sys/firmware/efi').is_dir() else 'bios'


def boot_medium():
    """The block device holding the running Live ISO and whether it is optical."""
    source = read_command(['findmnt', '-n', '-o', 'SOURCE', str(BOOTMNT)]).strip()
    kind, parent = (read_command(['lsblk', '-n', '-o', 'TYPE,PKNAME', source]).split() + [''])[:2]
    if kind == 'part' and parent:
        # A hybrid ISO written to a USB stick boots from the whole device.
        source = '/dev/' + parent
        kind = read_command(['lsblk', '-n', '-d', '-o', 'TYPE', source]).strip()
    return source, kind == 'rom'


def guest_cmdline():
    """Reuse the Live medium's archiso parameters; run the headless guest target."""
    keep = [token for token in Path('/proc/cmdline').read_text().split()
            if token.startswith('archiso') or token.startswith('cow_')]
    return ' '.join([*keep, GUEST_OPTIONS])


def marker_present():
    return Path('/sys/firmware/qemu_fw_cfg/by_name/opt/org.agi-os.test/raw').exists()


def guest_kernel():
    tokens = dict(t.split('=', 1) for t in Path('/proc/cmdline').read_text().split() if '=' in t)
    boot = BOOTMNT / tokens.get('archisobasedir', 'arch') / 'boot/x86_64'
    return boot / 'vmlinuz-linux', boot / 'initramfs-linux.img'


class VirtualMachine:
    def __init__(self, image, memory=4096, cpus=4, firmware=None, directory=None):
        if image.get('format') not in ('qcow2', 'raw') or not isinstance(image.get('path'), str):
            raise ValueError('Некорректное описание образа превью')
        self.image = image
        self.firmware = firmware or live_firmware()
        self.directory = directory or DATA_ROOT / 'vm' / ('web-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=directory is not None)
        self.memory, self.cpus = memory, cpus
        self.vnc_port = available_port()
        self.process = None
        self.log = None
        self.server = None
        self.connection = None
        self.reader = self.writer = None

    def describe(self):
        return {'directory': str(self.directory), 'image': self.image,
                'firmware': self.firmware, 'memory': self.memory, 'cpus': self.cpus}

    @classmethod
    def restore(cls, saved):
        directory = Path(saved['directory']).resolve()
        if directory.parent != (DATA_ROOT / 'vm').resolve() or not directory.name.startswith('web-'):
            raise ValueError('Некорректный путь VM')
        return cls(saved['image'], saved.get('memory', 4096), saved.get('cpus', 4), saved.get('firmware'), directory)

    @property
    def running(self):
        return self.process is not None and self.process.returncode is None

    async def start(self, install=True):
        if not live_environment():
            raise RuntimeError('VM создаётся только внутри загруженной Live-среды AGIOS')
        if not Path('/dev/kvm').exists():
            raise RuntimeError('Аппаратная виртуализация недоступна. Включите Intel VT-x / AMD-V в настройках '
                               'UEFI/BIOS компьютера и загрузите AGIOS снова.')
        path = Path(self.image['path'])
        if not (path.is_file() or path.is_block_device()):
            raise RuntimeError('Хранилище превью недоступно: ' + str(path))
        cache = ',cache=none' if path.is_block_device() else ''
        args = ['qemu-system-x86_64', '-name', 'AGIOS local preview', '-machine', 'q35',
                '-accel', 'kvm', '-cpu', 'host', '-m', str(self.memory), '-smp', str(self.cpus),
                '-display', 'none', '-device', 'virtio-vga', '-vnc', f'127.0.0.1:{self.vnc_port - 5900}',
                '-device', 'qemu-xhci', '-device', 'usb-tablet',
                '-device', 'virtio-balloon-pci,free-page-reporting=on',
                '-nic', 'user,model=virtio-net-pci',
                '-drive', f'file={path},format={self.image["format"]},if=none,id=system,discard=unmap,detect-zeroes=unmap{cache}',
                '-device', f'virtio-blk-pci,drive=system,bootindex={2 if install else 1}',
                '-qmp', f'unix:{self.directory}/qmp.sock,server=on,wait=off']
        if self.firmware == 'uefi':
            code, nvram = OVMF / 'OVMF_CODE.4m.fd', self.directory / 'OVMF_VARS.fd'
            if not nvram.exists():
                shutil.copyfile(OVMF / 'OVMF_VARS.4m.fd', nvram)
            args += ['-drive', f'if=pflash,format=raw,readonly=on,file={code}',
                     '-drive', f'if=pflash,format=raw,file={nvram}']
        if install:
            medium, optical = await asyncio.to_thread(boot_medium)
            kernel, initrd = guest_kernel()
            if not kernel.is_file() or not initrd.is_file():
                raise RuntimeError('На загрузочном носителе нет ядра Live для установочной VM')
            if optical:
                args += ['-drive', f'file={medium},media=cdrom,readonly=on,if=none,id=live',
                         '-device', 'ide-cd,drive=live,bootindex=1']
            else:
                args += ['-drive', f'file={medium},format=raw,readonly=on,if=none,id=live',
                         '-device', 'virtio-blk-pci,drive=live,bootindex=1']
            cmdline = guest_cmdline()
            mirror = Path('/sys/firmware/qemu_fw_cfg/by_name/opt/org.agi-os.test-mirror/raw')
            if marker_present() and mirror.exists():
                # Test-only: a pinned mirror for the guest's choose-mirror service (fw_cfg is root-readable).
                import subprocess
                value = subprocess.run(['sudo', '-n', 'cat', str(mirror)], capture_output=True, text=True, timeout=10).stdout.strip()
                if value:
                    cmdline += ' mirror=' + value
            cmdline += ' console=ttyS0'
            args += ['-kernel', str(kernel), '-initrd', str(initrd), '-append', cmdline,
                     '-serial', f'file:{self.directory}/guest-console.log']
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
            path.unlink(missing_ok=True)
            self.server = await asyncio.start_unix_server(connect, path=str(path), limit=1_000_000)
            args += ['-device', 'virtio-serial-pci', '-chardev', f'socket,id=install,path={path}',
                     '-device', 'virtserialport,chardev=install,name=org.agi-os.install']
        self.log = (self.directory / 'qemu.log').open('ab')
        self.process = await asyncio.create_subprocess_exec(*args, stdout=self.log, stderr=self.log)
        await asyncio.sleep(.5)
        if not self.running:
            raise RuntimeError('QEMU не запустился: ' + (self.directory / 'qemu.log').read_text()[-1500:])

    async def install(self, config, password, passphrase, notify):
        await asyncio.wait_for(self.connection, 180)
        ready = json.loads(await asyncio.wait_for(self.reader.readline(), 240))
        if ready.get('kind') != 'ready':
            raise RuntimeError('Установочная VM не готова')
        inner = next((d for d in ready['inventory']['disks'] if d['path'] == '/dev/vda' and d['eligible']), None)
        if inner is None:
            raise RuntimeError('Установочная VM не видит хранилище превью')
        if ready['inventory']['firmware'] != self.firmware:
            raise RuntimeError('Тип загрузки установочной VM не совпадает с компьютером')
        # Inside the VM the preview storage is /dev/vda; consent is re-bound to that view.
        translated = type(config).parse({**config.as_dict(), 'disk': '/dev/vda'})
        request = {'configuration': translated.as_dict(), 'consent_digest': translated.digest(),
                   'fingerprint': inner['fingerprint'], 'password': password, 'passphrase': passphrase}
        self.writer.write(json.dumps(request).encode() + b'\n')
        await self.writer.drain()
        del request, password, passphrase
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
        await self.wait_exit()
        await self.close_channel()
        self.log.close()
        await self.start(install=False)

    async def qmp(self, command):
        reader, writer = await asyncio.open_unix_connection(str(self.directory / 'qmp.sock'))
        try:
            await reader.readline()
            for payload in ({'execute': 'qmp_capabilities'}, {'execute': command}):
                writer.write(json.dumps(payload).encode() + b'\n')
                await writer.drain()
                await reader.readline()
        finally:
            writer.close()

    async def wait_exit(self):
        """The guest has unmounted its disk and asked to power off; give QEMU time, then end it."""
        try:
            await asyncio.wait_for(self.process.wait(), 240)
            return
        except TimeoutError:
            pass
        try:
            await self.qmp('quit')
            await asyncio.wait_for(self.process.wait(), 20)
        except (OSError, TimeoutError):
            self.process.kill()
            await self.process.wait()

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
