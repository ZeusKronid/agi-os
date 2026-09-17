#!/usr/bin/env python3
"""Test-only localhost transport to the Live VM serial instrumentation."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import threading
import time

spec=importlib.util.spec_from_file_location('qa_client',Path(__file__).with_name('qa-client.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
for _ in range(300):
    try:
        client=module.QAClient()
        break
    except OSError:time.sleep(1)
else:raise SystemExit('External test VM serial channel unavailable')
lock=threading.Lock()
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        try:
            with lock:result=client.call(**data)
            payload=json.dumps({'result':result},ensure_ascii=False).encode()
        except Exception as exc:payload=json.dumps({'error':str(exc)}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
ThreadingHTTPServer(('127.0.0.1',19876),Handler).serve_forever()
