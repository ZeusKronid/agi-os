#!/usr/bin/env python3
"""Host-side test client for the external Live VM's private serial channel."""
import json
from pathlib import Path
import socket
import uuid

ROOT = Path(__file__).resolve().parents[2]

class QAClient:
    def __init__(self):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(600)
        self.socket.connect(str(ROOT/'.local/live-test/qa.sock'))
        self.stream = self.socket.makefile('rb')
        while True:
            ready = json.loads(self.stream.readline())
            if ready.get('ready'): break

    def call(self, method, **data):
        request_id = uuid.uuid4().hex
        self.socket.sendall(json.dumps({'id':request_id,'method':method,**data}).encode()+b'\n')
        while line := self.stream.readline(2_000_000):
            answer = json.loads(line)
            if answer.get('id') != request_id: continue
            if 'error' in answer: raise RuntimeError(answer['error'])
            return answer['result']
        raise RuntimeError('QA channel closed')

    def close(self):
        self.stream.close()
        self.socket.close()

if __name__ == '__main__':
    import sys
    client = QAClient()
    try:
        print(json.dumps(client.call('exec',args=sys.argv[1:]),ensure_ascii=False,indent=2))
    finally:
        client.close()
