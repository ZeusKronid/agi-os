#!/usr/bin/env python3
"""Explicitly enabled test instrumentation; never exposed through the website."""
import json
import io
from pathlib import Path
import subprocess
import time
import urllib.request

port = Path('/dev/virtio-ports/org.agi-os.qa')
while not port.exists():
    time.sleep(.3)
with port.open('r+b', buffering=0) as channel:
    channel.write(b'{"ready":true}\n')
    reader = io.BufferedReader(channel, buffer_size=65536)
    while True:
        raw = reader.readline(1_000_000)
        if not raw:
            time.sleep(.1)
            continue
        request = json.loads(raw)
        try:
            method = request['method']
            if method == 'http':
                endpoint = request['path']
                if not endpoint.startswith('/api/'):
                    raise ValueError('Only the local AGIOS API is available')
                body = request.get('body')
                req = urllib.request.Request('http://127.0.0.1:8787' + endpoint,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'Content-Type':'application/json', 'X-AGIOS':'local'})
                with urllib.request.urlopen(req, timeout=600) as response:
                    result = json.load(response)
            elif method == 'exec':
                process = subprocess.run(request['args'], capture_output=True, text=True,
                                         timeout=request.get('timeout', 30))
                result = {'code':process.returncode, 'stdout':process.stdout[-100000:], 'stderr':process.stderr[-10000:]}
            elif method == 'spawn':
                log = open('/tmp/agi-qa-process.log','ab')
                process = subprocess.Popen(request['args'], stdout=log, stderr=log, start_new_session=True)
                result = {'pid':process.pid}
                log.close()
            else:
                raise ValueError('Unknown test operation')
            answer = {'id':request['id'], 'result':result}
        except Exception as exc:
            answer = {'id':request.get('id'), 'error':str(exc)}
        pending = memoryview(json.dumps(answer, ensure_ascii=False).encode() + b'\n')
        while pending:
            pending = pending[channel.write(pending):]
