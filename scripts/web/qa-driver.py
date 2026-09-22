#!/usr/bin/env python3
"""Host-side test driver: QA serial channel + QMP screenshots/input of the outer test VM."""
import base64
import importlib.util
import io
import json
from pathlib import Path
import socket
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('qa_client', Path(__file__).with_name('qa-client.py'))
qa_client = importlib.util.module_from_spec(spec); spec.loader.exec_module(qa_client)


class QMP:
    def __init__(self, path=ROOT / '.local/live-test/qmp.sock'):
        self.sock = socket.socket(socket.AF_UNIX); self.sock.settimeout(30); self.sock.connect(str(path))
        self.stream = self.sock.makefile('rb')
        self.stream.readline()
        self.execute('qmp_capabilities')

    def execute(self, command, **arguments):
        self.sock.sendall(json.dumps({'execute': command, 'arguments': arguments}).encode() + b'\n')
        while True:
            answer = json.loads(self.stream.readline())
            if 'return' in answer: return answer['return']
            if 'error' in answer: raise RuntimeError(answer['error'])

    def screenshot(self, path):
        from PIL import Image
        temp = ROOT / '.local/live-test/screendump.ppm'
        self.execute('screendump', filename=str(temp), format='png')
        image = Image.open(temp); image.load(); image.save(path); return image

    def keys(self, *names, hold=40):
        self.execute('send-key', keys=[{'type': 'qcode', 'data': n} for n in names], **{'hold-time': hold})
        time.sleep(0.06)

    def type(self, text, delay=0.03):
        shifted = dict(zip('~!@#$%^&*()_+{}|:"<>?', '`1234567890-=[]\\;\',./'))
        names = {' ': 'spc', '-': 'minus', '=': 'equal', '[': 'bracket_left', ']': 'bracket_right', ';': 'semicolon', "'": 'apostrophe',
                 '`': 'grave_accent', '\\': 'backslash', ',': 'comma', '.': 'dot', '/': 'slash', '\n': 'ret', '\t': 'tab'}
        for char in text:
            shift = char.isupper() or char in shifted
            base = shifted.get(char, char.lower())
            key = names.get(base, base)
            self.keys('shift', key) if shift else self.keys(key)
            time.sleep(delay)

    def click(self, x, y, button='left'):
        self.execute('input-send-event', events=[{'type': 'abs', 'data': {'axis': 'x', 'value': int(x * 32767)}},
                                                 {'type': 'abs', 'data': {'axis': 'y', 'value': int(y * 32767)}}])
        time.sleep(0.1)
        self.execute('input-send-event', events=[{'type': 'btn', 'data': {'down': True, 'button': button}}])
        time.sleep(0.08)
        self.execute('input-send-event', events=[{'type': 'btn', 'data': {'down': False, 'button': button}}])
        time.sleep(0.1)


def qa(retries=600):
    for _ in range(retries):
        try: return qa_client.QAClient()
        except OSError: time.sleep(1)
    raise SystemExit('QA channel unavailable')


def api(client, path, body=None):
    return client.call('http', path=path, body=body)


def wait_state(client, predicate, timeout=3600, every=3):
    end = time.time() + timeout
    while time.time() < end:
        state = api(client, '/api/state')
        if predicate(state): return state
        time.sleep(every)
    raise TimeoutError('state condition not met; last status: ' + state.get('status', ''))


def push_file(client, path, local, mode='644', owner='root:root'):
    """Copy a host file into the Live through the QA channel (test iteration without rebuilding)."""
    data = base64.b64encode(Path(local).read_bytes()).decode()
    return client.call('exec', args=['sudo', 'bash', '-c', f'echo {data} | base64 -d > {path} && chmod {mode} {path} && chown {owner} {path}'])
