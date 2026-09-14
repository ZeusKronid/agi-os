"""Development-only provider over a dedicated QEMU virtio serial channel."""
import json
import os
from pathlib import Path
import select
import threading
import time
import uuid

from providers import ProviderError
from domain import validate_reply

PORT = Path('/dev/virtio-ports/org.agi-os.llm')
LIMIT = 250_000


class BridgeProvider:
    def __init__(self, path=PORT):
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY)
        self.model = ''
        self.lock = threading.Lock()
        self.closed = threading.Event()

    def request(self, method, **params):
        with self.lock:
            if self.closed.is_set():
                raise ProviderError('Мост отключён')
            request_id = uuid.uuid4().hex
            outgoing = json.dumps({'id': request_id, 'method': method, **params}, ensure_ascii=False).encode() + b'\n'
            if len(outgoing) > LIMIT:
                raise ProviderError('Диалог слишком большой для моста')
            end = time.monotonic() + (15 if method == 'models' else 240)
            received = b''
            try:
                while time.monotonic() < end and not self.closed.is_set():
                    readable, writable, _ = select.select([self.fd], [self.fd] if outgoing else [], [], .2)
                    if writable:
                        outgoing = outgoing[os.write(self.fd, outgoing):]
                    if readable:
                        chunk = os.read(self.fd, 65536)
                        if not chunk:
                            raise OSError()
                        received += chunk
                        if len(received) > LIMIT:
                            raise OSError()
                        while b'\n' in received:
                            line, received = received.split(b'\n', 1)
                            reply = json.loads(line)
                            if reply.get('id') != request_id:
                                continue  # Ignore an old response after reconnect/cancellation.
                            if 'error' in reply:
                                raise ProviderError('Мост не получил ответ. Проверьте вход Codex на хосте, сеть и лимиты.')
                            return reply['result']
            except (OSError, ValueError, KeyError, TypeError):
                raise ProviderError('Канал моста недоступен. Переподключитесь или перезапустите тестовую VM.') from None
            raise ProviderError('Истекло время ожидания моста')

    def models(self):
        models = self.request('models')
        if not isinstance(models, list) or not models or any(not isinstance(m, str) for m in models):
            raise ProviderError('Мост вернул неверный список моделей')
        return models

    def reply(self, system, messages):
        return validate_reply(self.request('reply', system=system, messages=messages))

    def close(self):
        self.closed.set()
        with self.lock:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
