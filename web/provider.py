"""Providers run in the Live environment. The serial bridge is test-only."""
from bridge import BridgeProvider, PORT
from chatgpt import ChatGPTProvider
from providers import PROVIDERS, ProviderError

CONTEXT = '''
AGIOS is running inside a booted Linux Live environment on the user's computer.
The system is installed directly onto ONE of this computer's physical disks listed
in the detected hardware (choose only an eligible one; the Live medium is never a
target). The app first installs the system into a preview (in memory, a file on
another medium or free space, as the user picks) and boots it as a virtual machine
inside Live (Apache Guacamole screen in the browser). After the user checks it and
gives separate explicit consent, the app puts it on the chosen disk: either erasing
the whole disk or next to the systems already on it (dual boot), then finalizes
boot for the real hardware and the computer restarts into the new system. Before
consent, nothing is written. The site privately collects the installed
user's password and the optional disk-encryption passphrase. Services must include
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

    # The controller hands over the page's cancel token. ChatGPT and the bridge stop their
    # request; an API request cannot be interrupted, so its late answer is discarded.
    cancellable = True

    def reply(self, system, messages, cancel=None):
        if self.backend is None:
            raise ProviderError('Connect a model: sign in to ChatGPT or add an API in the model settings')
        self.backend.model = self.model
        if getattr(self.backend, 'cancellable', False):
            return self.backend.reply(system + CONTEXT, messages, cancel=cancel)
        return self.backend.reply(system + CONTEXT, messages)

    def close(self):
        if self.backend:
            self.backend.close()

    @property
    def label(self):
        """Which service answers, for the page's status line."""
        if self.backend is None:
            return ''
        if isinstance(self.backend, ChatGPTProvider):
            return PROVIDERS['chatgpt'][0]
        if isinstance(self.backend, BridgeProvider):
            return 'Test bridge'
        return PROVIDERS.get(getattr(self.backend, 'kind', ''), ('',))[0]


def connect_chatgpt(model=None, show_login=lambda url: None):
    """Sign in to ChatGPT. The site runs as a system user without the Live desktop,
    so the sign-in page is opened by the browser tab of the site (show_login)."""
    if PORT.exists():
        provider = LiveProvider()
        if model:
            provider.model = model
        return provider
    backend = ChatGPTProvider()
    try:
        models = backend.login(show_login)
        backend.model = model or models[0]
        return LiveProvider(backend)
    except Exception:
        backend.close()
        raise
