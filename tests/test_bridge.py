"""Bridge boundaries and real character-device framing, without paid inference."""
import importlib.util
import json
import os
from pathlib import Path
import pty
import sys
import tempfile
import threading
import tty
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'archiso/airootfs/usr/local/share/agi-os/installer'))
from bridge import BridgeProvider
from providers import ProviderError
from chatgpt import ChatGPTProvider
spec = importlib.util.spec_from_file_location('dev_bridge', ROOT / 'scripts/dev-bridge.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class BridgeTests(unittest.TestCase):
    def test_only_models_and_valid_dialogue_allowed(self):
        b = host.Bridge('test-model')
        self.assertEqual(b.dispatch({'method': 'models'}), ['test-model'])
        for r in ({'method': 'command/exec'}, {'method': 'account/read'},
                  {'method': 'reply', 'system': '', 'messages': []},
                  {'method': 'reply', 'system': '', 'messages': [{'role': 'system', 'content': 'x'}]}):
            with self.assertRaises(ProviderError):
                b.dispatch(r)
        self.assertIsNone(b.provider)

    def test_host_tokens_reload_without_refresh_token_or_file_mutation(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'CODEX_HOME': folder}):
            path = Path(folder) / 'auth.json'
            for access in ('first', 'updated'):
                contents = json.dumps({'tokens': {'access_token': access,
                    'account_id': 'account', 'refresh_token': 'never-forward'}})
                path.write_text(contents)
                self.assertEqual(host.host_tokens(), {'accessToken': access, 'chatgptAccountId': 'account'})
                self.assertEqual(path.read_text(), contents)

    def test_backend_errors_are_redacted_and_backend_discarded(self):
        b = host.Bridge('test-model')
        with patch.object(host, 'ChatGPTProvider') as cls, patch.object(host, 'host_tokens', return_value={}):
            cls.return_value.rpc.side_effect = RuntimeError('SECRET_VALUE')
            with self.assertRaises(ProviderError) as error:
                b.dispatch({'method': 'reply', 'system': 's', 'messages': [{'role': 'user', 'content': 'x'}]})
            self.assertNotIn('SECRET_VALUE', str(error.exception))
            cls.return_value.close.assert_called_once()
            self.assertIsNone(b.provider)

    def test_serial_partial_frames_stale_reply_and_reconnect(self):
        master, slave = pty.openpty()
        tty.setraw(slave)
        path = os.ttyname(slave)
        errors = []
        def respond():
            try:
                for _ in range(2):
                    data = b''
                    while not data.endswith(b'\n'):
                        data += os.read(master, 4096)
                    request = json.loads(data)
                    payload = (json.dumps({'id': 'stale', 'result': ['wrong']}) + '\n' +
                               json.dumps({'id': request['id'], 'result': ['test-model']}) + '\n').encode()
                    for start in range(0, len(payload), 7):
                        os.write(master, payload[start:start + 7])
            except Exception as e:
                errors.append(e)
        thread = threading.Thread(target=respond, daemon=True)
        thread.start()
        try:
            for _ in range(2):
                provider = BridgeProvider(path)
                try:
                    self.assertEqual(provider.models(), ['test-model'])
                finally:
                    provider.close()
                    provider.close()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
        finally:
            os.close(master)
            os.close(slave)

    def test_refresh_does_not_switch_account(self):
        import queue
        provider = object.__new__(ChatGPTProvider)
        provider.token_source = lambda: {'accessToken': 'private', 'chatgptAccountId': 'new-account'}
        provider.events = queue.Queue()
        provider.events.put({'id': 7, 'method': 'account/chatgptAuthTokens/refresh',
            'params': {'previousAccountId': 'old-account'}})
        with patch.object(provider, 'send') as send:
            provider.next_event()
            response = send.call_args.args[0]
            self.assertIn('error', response)
            self.assertNotIn('private', json.dumps(response))


if __name__ == '__main__':
    unittest.main()
