#!/usr/bin/env python3
"""Headless guest of the preview VM: runs the installer over its private virtio port.

Started by agi-guest.service only when the Live medium boots with `agios.guest`.
"""
import json
from pathlib import Path
import subprocess
import sys
import time

ENGINE = Path('/usr/local/share/agi-os/installer')
sys.path.insert(0, str(ENGINE))
from journal import Logger
from system import inventory

LOG = Logger('guest')


def main():
    port = Path('/dev/virtio-ports/org.agi-os.install')
    while not port.exists():
        time.sleep(.5)
    marker = Path('/sys/firmware/qemu_fw_cfg/by_name/opt/org.agi-os.test-cache/raw')
    if marker.exists() and marker.read_bytes() == b'1':
        cache = Path('/dev/disk/by-label/AGIOS_CACHE')
        if not cache.exists():
            raise RuntimeError('Requested QA package cache is unavailable')
        target = Path('/run/agi-test-cache')
        target.mkdir(exist_ok=True)
        subprocess.run(['mount', '-o', 'ro', str(cache), str(target)], check=True)
        conf = Path('/etc/pacman.conf')
        conf.write_text(conf.read_text().replace('Include = /etc/pacman.d/mirrorlist',
                                                 'Server = file:///run/agi-test-cache'))
        # pacstrap uses this live config, but the installed system retains its
        # normal packaged pacman.conf and the unchanged official mirrorlist.
    with port.open('r+b', buffering=0) as channel:
        def send(value):
            channel.write(json.dumps(value, ensure_ascii=False).encode() + b'\n')
        send({'kind': 'ready', 'inventory': inventory()})
        LOG.info('guest.ready', 'Установочная VM готова, жду запрос')
        raw = channel.readline(1_000_001)
        request = json.loads(raw)
        LOG.info('guest.request', 'Запрос установки получен')
        if request['configuration']['disk'] != '/dev/vda':
            raise ValueError('Only the VM disk is supported')
        proc = subprocess.Popen([sys.executable, '-u', str(ENGINE / 'worker.py')],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        proc.stdin.write(json.dumps(request) + '\n')
        proc.stdin.flush()
        request.pop('password', None)
        request.pop('passphrase', None)
        installed = False
        try:
            for line in proc.stdout:
                event = json.loads(line)
                send(event)
                installed |= event.get('kind') == 'installed'
        except (OSError, ValueError):
            proc.stdin.write('{"cancel": true}\n')
            proc.stdin.flush()
            raise
        finally:
            proc.wait()
            proc.stdin.close()
            LOG.log('info' if installed and proc.returncode == 0 else 'error', 'guest.worker-exit',
                    f'Установщик завершился с кодом {proc.returncode}', installed=installed)
        if installed and proc.returncode == 0:
            send({'kind': 'shutdown', 'text': 'Booting the installed system'})
            subprocess.run(['systemctl', 'poweroff'], check=True)


if __name__ == '__main__':
    main()
