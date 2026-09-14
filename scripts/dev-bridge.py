#!/usr/bin/env python3
"""Private QEMU serial bridge. No network listener, credentials, or raw RPC in guest."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
    'archiso/airootfs/usr/local/share/agi-os/installer'))
from chatgpt import ChatGPTProvider
from providers import ProviderError

LIMIT = 250_000


def host_tokens():
    # Only access token + account ID enter the isolated backend's memory.
    # The host Codex owns refresh_token rotation; never copy or refresh it here.
    try:
        home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        tokens = json.loads((home / 'auth.json').read_text())['tokens']
        access, account = tokens['access_token'], tokens['account_id']
        if not isinstance(access, str) or not access or not isinstance(account, str) or not account:
            raise ValueError()
        return {'accessToken': access, 'chatgptAccountId': account}
    except Exception:
        raise ProviderError('Вход Codex на хосте недоступен. Войдите в Codex на хосте.') from None


def host_model():
    home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    try:
        return tomllib.loads((home / 'config.toml').read_text())['model']
    except Exception:
        raise ProviderError('Укажите --model или настройте модель Codex на хосте') from None


class Bridge:
    def __init__(self, model):
        self.model = model
        self.provider = None

    def close(self):
        if self.provider:
            self.provider.close()
            self.provider = None

    def dispatch(self, request):
        if not isinstance(request, dict):
            raise ProviderError('Некорректный запрос моста')
        if request.get('method') == 'models':
            return [self.model]
        if request.get('method') != 'reply':
            raise ProviderError('Метод моста запрещён')
        system, messages = request.get('system'), request.get('messages')
        if (not isinstance(system, str) or len(system) > 30000 or
                not isinstance(messages, list) or not 1 <= len(messages) <= 500 or
                any(not isinstance(m, dict) or set(m) != {'role', 'content'} or
                    m['role'] not in ('user', 'assistant') or not isinstance(m['content'], str)
                    for m in messages)):
            raise ProviderError('Некорректный диалог')
        try:
            if self.provider is None:
                self.provider = ChatGPTProvider(token_source=host_tokens)
            # Reload the host's latest token before every turn and on refresh requests.
            self.provider.rpc('account/login/start', {'type': 'chatgptAuthTokens', **host_tokens()})
            self.provider.model = self.model
            return self.provider.reply(system, messages)
        except Exception:
            self.close()
            raise ProviderError('Мост не получил ответ. Проверьте вход Codex на хосте, сеть и лимиты; повторите запрос.') from None


def serve(path, bridge):
    # Parent must be owned by this user and private. Never unlink a live/stale socket
    # supplied by a caller; run-vm allocates a unique private runtime directory.
    parent = path.parent.stat()
    if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise ProviderError('Каталог сокета должен принадлежать пользователю и иметь права 0700')
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(1)
        print('Development LLM bridge ready', flush=True)
        while True:
            conn, _ = server.accept()
            with conn, conn.makefile('rb') as stream:
                while True:
                    line = stream.readline(LIMIT + 1)
                    if not line or len(line) > LIMIT or not line.endswith(b'\n'):
                        break
                    request_id = None
                    try:
                        request = json.loads(line)
                        request_id = request.get('id') if isinstance(request, dict) else None
                        if not isinstance(request_id, str) or len(request_id) > 64:
                            raise ProviderError('Некорректный идентификатор запроса')
                        response = {'id': request_id, 'result': bridge.dispatch(request)}
                    except Exception:
                        response = {'id': request_id, 'error': 'Мост не выполнил запрос. Проверьте вход Codex на хосте, сеть и лимиты.'}
                    try:
                        conn.sendall(json.dumps(response, ensure_ascii=False).encode() + b'\n')
                    except OSError:
                        break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--model')
    args = parser.parse_args()
    bridge = Bridge(args.model or host_model())
    def stop(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    try:
        host_tokens()  # Fail before QEMU starts if the host has never signed in.
        serve(args.socket, bridge)
    except Exception:
        print('Cannot start development bridge: check host Codex login and private socket directory', file=sys.stderr)
        return 1
    finally:
        bridge.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
