"""Providers run in the Live environment. The serial bridge is test-only."""
import subprocess
from bridge import BridgeProvider, PORT
from chatgpt import ChatGPTProvider
from providers import ProviderError

CONTEXT = '''
AGIOS is running inside a booted Linux Live environment. Its localhost website
and QEMU run in this Live environment. You are planning a NEW preview VM, not
installing onto the live computer's physical disks. Only a blank virtual /dev/vda
is available. It contains no existing user data. The site privately collects the
installed user's password. Preview uses Apache Guacamole. Services must include
.service suffixes; decoded file contents must contain actual newline characters.
'''


class LiveProvider:
    def __init__(self, backend=None):
        self.backend = backend
        self.model = ''
        if backend is None and PORT.exists():
            self.backend = BridgeProvider()
            self.model = self.backend.models()[0]
        elif backend:
            self.model = backend.model

    def reply(self, system, messages):
        if self.backend is None:
            raise ProviderError('Подключите модель: войдите в ChatGPT или укажите API в настройках сайта')
        self.backend.model = self.model
        return self.backend.reply(system + CONTEXT, messages)

    def close(self):
        if self.backend:
            self.backend.close()


def connect_chatgpt(model=None):
    if PORT.exists():
        provider = LiveProvider()
        if model:
            provider.model = model
        return provider
    backend = ChatGPTProvider()
    try:
        models = backend.login(lambda url: subprocess.Popen(
            ['xdg-open', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        backend.model = model or models[0]
        return LiveProvider(backend)
    except Exception:
        backend.close()
        raise
