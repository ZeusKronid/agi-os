#!/usr/bin/env python3
"""Smoke-boot an AGIOS Live ISO in a headless QEMU and check that the Live came up.

The VM carries the test fw_cfg marker and the private QA serial port, so the Live
starts its test-only instrumentation (agi-qa.service, after agi-web.service). The
check passes when, within the timeout:
  * the QA agent inside the Live answers,
  * agi-web.service, agi-guacd.service and the display manager are active,
  * the website answers GET /api/state with JSON and GET /api/version with the
    expected version (optional),
  * optionally, the image reports the expected source revision.
No model, no target disk writes; the VM gets a blank scratch disk only so the
storage view is realistic. Uses KVM when /dev/kvm is usable, otherwise TCG (slow).

    scripts/ci/smoke-boot.py out/agi-os-*.iso --firmware uefi --logs out/smoke-uefi
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

OVMF = [  # (code, vars) pairs: Arch, Debian/Ubuntu, Fedora layouts.
    ('/usr/share/edk2/x64/OVMF_CODE.4m.fd', '/usr/share/edk2/x64/OVMF_VARS.4m.fd'),
    ('/usr/share/OVMF/OVMF_CODE_4M.fd', '/usr/share/OVMF/OVMF_VARS_4M.fd'),
    ('/usr/share/edk2/ovmf/OVMF_CODE.fd', '/usr/share/edk2/ovmf/OVMF_VARS.fd'),
    ('/usr/share/OVMF/OVMF_CODE.fd', '/usr/share/OVMF/OVMF_VARS.fd'),
]
REQUIRED_UNITS = ('agi-guacd.service', 'agi-web.service', 'display-manager.service')
POLL = 3  # seconds between retries of a check that may still be settling


def log(message):
    print(f'[smoke {time.strftime("%H:%M:%S")}] {message}', flush=True)


def ovmf():
    for code, variables in OVMF:
        if Path(code).is_file() and Path(variables).is_file():
            return code, variables
    raise SystemExit('UEFI firmware (OVMF) not found; install edk2-ovmf or ovmf')


def kvm_usable():
    return os.access('/dev/kvm', os.R_OK | os.W_OK)


def qemu_command(iso, firmware, memory, cpus, workdir):
    accel = ['-accel', 'kvm', '-cpu', 'host'] if kvm_usable() else ['-accel', 'tcg', '-cpu', 'max']
    scratch = workdir / 'scratch.qcow2'
    subprocess.run(['qemu-img', 'create', '-q', '-f', 'qcow2', str(scratch), '20G'], check=True)
    command = ['qemu-system-x86_64', '-name', f'AGIOS smoke ({firmware})', '-machine', 'q35', *accel,
               '-m', str(memory), '-smp', str(cpus), '-display', 'none', '-vga', 'std',
               '-serial', f'file:{workdir / "serial.log"}',
               '-qmp', f'unix:{workdir / "qmp.sock"},server=on,wait=off',
               '-nic', 'user,model=virtio-net-pci',
               '-fw_cfg', 'name=opt/org.agi-os.test,string=1',
               '-device', 'virtio-serial-pci',
               '-chardev', f'socket,id=qa,path={workdir / "qa.sock"},server=on,wait=off',
               '-device', 'virtserialport,chardev=qa,name=org.agi-os.qa',
               '-drive', f'file={scratch},format=qcow2,if=none,id=target',
               '-device', 'virtio-blk-pci,drive=target,serial=AGIOS_TARGET',
               '-drive', f'file={iso},media=cdrom,readonly=on,if=none,id=live',
               '-device', 'ide-cd,drive=live,bootindex=1']
    if firmware == 'uefi':
        code, variables = ovmf()
        shutil.copyfile(variables, workdir / 'OVMF_VARS.fd')
        command += ['-drive', f'if=pflash,format=raw,readonly=on,file={code}',
                    '-drive', f'if=pflash,format=raw,file={workdir / "OVMF_VARS.fd"}']
    return command


class QA:
    """Client of the Live's private QA serial channel (see scripts/web/qa-guest.py)."""

    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.connect(str(path))
        self.stream = self.socket.makefile('rb')

    def wait_ready(self, deadline):
        # The guest announces itself once with {"ready": true}; nothing arrives before it starts.
        while time.monotonic() < deadline:
            self.socket.settimeout(max(1, deadline - time.monotonic()))
            try:
                line = self.stream.readline(1_000_000)
            except (socket.timeout, TimeoutError):
                break
            if not line:
                raise RuntimeError('QA channel closed')
            try:
                if json.loads(line).get('ready'):
                    return
            except ValueError:
                continue
        raise TimeoutError('the Live QA agent did not answer in time')

    def call(self, method, timeout=120, **data):
        request_id = uuid.uuid4().hex
        self.socket.settimeout(timeout)
        self.socket.sendall(json.dumps({'id': request_id, 'method': method, **data}).encode() + b'\n')
        while line := self.stream.readline(2_000_000):
            answer = json.loads(line)
            if answer.get('id') != request_id:
                continue
            if 'error' in answer:
                raise RuntimeError(answer['error'])
            return answer['result']
        raise RuntimeError('QA channel closed')

    def run(self, *args, timeout=60):
        return self.call('exec', args=list(args), timeout=timeout + 10)

    def close(self):
        self.stream.close()
        self.socket.close()


def qmp(path, command, **arguments):
    with socket.socket(socket.AF_UNIX) as channel:
        channel.settimeout(30)
        channel.connect(str(path))
        stream = channel.makefile('rb')
        stream.readline()
        for request in ({'execute': 'qmp_capabilities'}, {'execute': command, 'arguments': arguments}):
            channel.sendall(json.dumps(request).encode() + b'\n')
            while line := stream.readline():
                if 'return' in json.loads(line) or 'error' in json.loads(line):
                    break


def check(qa, expect_revision, deadline, expect_version=''):
    failures = []
    for unit in REQUIRED_UNITS:
        # agi-web restarts on failure; give units until the deadline to settle as active.
        while True:
            state = qa.run('systemctl', 'is-active', unit)['stdout'].strip()
            if state == 'active' or time.monotonic() > deadline:
                break
            time.sleep(POLL)
        log(f'{unit}: {state}')
        if state != 'active':
            failures.append(f'{unit} is {state}')
    while True:
        try:
            state = qa.call('http', path='/api/state', timeout=60)
            log(f'/api/state answered: phase={state.get("phase")!r}')
            if not isinstance(state, dict):
                failures.append('/api/state did not return a JSON object')
            break
        except RuntimeError as error:
            if time.monotonic() > deadline:
                failures.append(f'/api/state failed: {error}')
                break
            time.sleep(POLL)
    try:
        version = qa.call('http', path='/api/version', timeout=60).get('version')
    except RuntimeError as error:
        version = None
        failures.append(f'/api/version failed: {error}')
    log(f'version reported by the Live: {version}')
    if expect_version and version != expect_version:
        failures.append(f'version {version!r} != expected {expect_version!r}')
    revision = qa.run('cat', '/usr/local/share/agi-os/source-revision')['stdout'].strip()
    log(f'source revision in the image: {revision or "missing"}')
    if expect_revision and revision != expect_revision:
        failures.append(f'source revision {revision!r} != expected {expect_revision!r}')
    system = qa.run('systemctl', 'is-system-running')['stdout'].strip()
    failed = qa.run('systemctl', 'list-units', '--failed', '--plain', '--no-legend')['stdout'].strip()
    log(f'system state: {system}; failed units: {failed or "none"}')
    journals = {}
    for line in failed.splitlines():
        unit = line.split()[0]
        # Diagnostics only: the QA agent may lack the rights to read the system journal.
        answer = qa.run('journalctl', '--boot', '--unit', unit, '--no-pager', '--lines', '40')
        journals[unit] = (answer['stdout'] + answer['stderr']).strip()
    return failures, {'system': system, 'failed_units': failed.splitlines(), 'source_revision': revision, 'version': version,
                      'failed_unit_journals': journals}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('iso', type=Path)
    parser.add_argument('--firmware', choices=('uefi', 'bios'), default='uefi')
    parser.add_argument('--memory', type=int, default=4096, help='MiB')
    parser.add_argument('--cpus', type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument('--timeout', type=int, default=0, help='seconds; default 600 with KVM, 2400 without')
    parser.add_argument('--expect-revision', default='')
    parser.add_argument('--expect-version', default='', help='v* tag or dev, as reported by /api/version')
    parser.add_argument('--logs', type=Path, help='directory for serial log, screenshot and result.json')
    args = parser.parse_args()
    if not args.iso.is_file():
        raise SystemExit(f'ISO not found: {args.iso}')
    timeout = args.timeout or (600 if kvm_usable() else 2400)
    logs = args.logs or Path(tempfile.mkdtemp(prefix='agios-smoke-logs.'))
    logs.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix='agios-smoke.'))
    command = qemu_command(args.iso.resolve(), args.firmware, args.memory, args.cpus, workdir)
    log(f'booting {args.iso.name} ({args.firmware}, {"KVM" if kvm_usable() else "TCG"}), timeout {timeout}s')
    started = time.monotonic()
    deadline = started + timeout
    qemu = subprocess.Popen(command, stdout=open(logs / 'qemu.log', 'wb'), stderr=subprocess.STDOUT)
    failures, details, qa = [], {}, None
    try:
        while not (workdir / 'qa.sock').exists():
            if qemu.poll() is not None:
                raise RuntimeError(f'QEMU exited with {qemu.returncode}; see {logs / "qemu.log"}')
            time.sleep(.2)
        qa = QA(workdir / 'qa.sock')
        qa.wait_ready(deadline)
        log(f'QA agent answered after {time.monotonic() - started:.0f}s')
        failures, details = check(qa, args.expect_revision, deadline, args.expect_version)
    except (RuntimeError, TimeoutError, OSError) as error:
        failures.append(str(error))
    finally:
        if qemu.poll() is None:
            if failures:
                try:
                    qmp(workdir / 'qmp.sock', 'screendump', filename=str(logs / 'screen.ppm'))
                except OSError as error:
                    log(f'screenshot failed: {error}')
            if qa:
                qa.close()
            qemu.terminate()
            try:
                qemu.wait(30)
            except subprocess.TimeoutExpired:
                qemu.kill()
                qemu.wait()
        shutil.copyfile(workdir / 'serial.log', logs / 'serial.log') if (workdir / 'serial.log').exists() else None
        shutil.rmtree(workdir, ignore_errors=True)
    result = {'iso': args.iso.name, 'firmware': args.firmware, 'kvm': kvm_usable(),
              'seconds': round(time.monotonic() - started), 'passed': not failures,
              'failures': failures, **details}
    (logs / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    for failure in failures:
        log(f'FAIL: {failure}')
    log('PASS' if not failures else f'logs: {logs}')
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())
