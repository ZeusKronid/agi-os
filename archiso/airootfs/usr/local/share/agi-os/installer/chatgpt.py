"""ChatGPT sign-in via the official Codex app-server, isolated from host disks.

The backend is only a conversation provider. Its entire home is an ephemeral
bubblewrap filesystem; no host Codex configuration or credentials are imported.
"""

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

from domain import REPLY_SCHEMA
from providers import ProviderError, parse_json_reply


class ChatGPTProvider:
    def __init__(self):
        if not shutil.which("bwrap") or not shutil.which("codex"):
            raise ProviderError("Для входа через ChatGPT нужны пакеты bubblewrap и openai-codex")
        home = str(Path.home())
        args = ["bwrap", "--unshare-all", "--share-net", "--die-with-parent", "--new-session",
                "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
                "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib", "/lib64",
                "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", home,
                "--chdir", home]
        for path in ("/etc/ssl", "/etc/ca-certificates", "/etc/resolv.conf", "/etc/hosts",
                     "/etc/nsswitch.conf", "/etc/passwd", "/etc/group", "/etc/localtime"):
            if Path(path).exists():
                args += ["--ro-bind", str(Path(path).resolve()), path]
        args += ["codex", "-c", 'cli_auth_credentials_store="ephemeral"',
                 "-c", "features.shell_tool=false", "-c", "features.multi_agent=false",
                 "-c", "features.apps=false", "-c", 'web_search="disabled"',
                 "app-server", "--listen", "stdio://"]
        env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG") if k in os.environ}
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
        self.events = queue.Queue()
        self.responses = {}
        self.ids = 0
        self.model = ""
        self.login_id = None
        self.thread_id = None
        threading.Thread(target=self._reader, daemon=True).start()
        self.rpc("initialize", {"clientInfo": {"name": "agi_os_installer", "title": "AGI OS Installer", "version": "0.2.0"}})
        self.send({"method": "initialized", "params": {}})

    def _reader(self):
        try:
            for line in self.proc.stdout:
                try:
                    self.events.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            self.events.put({"closed": True})

    def send(self, payload):
        try:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise ProviderError("Соединение ChatGPT закрыто") from None

    def next_event(self, timeout=120):
        try:
            event = self.events.get(timeout=timeout)
        except queue.Empty:
            raise ProviderError("Истекло время ожидания ChatGPT") from None
        if event.get("closed"):
            raise ProviderError("Служба ChatGPT завершилась. Проверьте поддержку bubblewrap и версию Codex.")
        if "id" in event and "method" in event:
            self.send({"id": event["id"], "error": {"code": -32601,
                "message": "Installer provider does not execute tools or approval requests"}})
        return event

    def rpc(self, method, params, timeout=30):
        self.ids += 1
        request_id = self.ids
        self.send({"id": request_id, "method": method, "params": params})
        end = time.monotonic() + timeout
        deferred = []
        try:
            while time.monotonic() < end:
                event = self.next_event(max(0.1, end - time.monotonic()))
                if event.get("id") == request_id and "method" not in event:
                    if "error" in event:
                        # Raw backend errors can contain configuration or auth data.
                        raise ProviderError("ChatGPT не выполнил запрос " + method)
                    return event.get("result", {})
                if "method" in event and "id" not in event:
                    deferred.append(event)
            raise ProviderError("Истекло время запроса ChatGPT")
        finally:
            for event in deferred:
                self.events.put(event)

    def login(self, open_browser):
        login = self.rpc("account/login/start", {"type": "chatgpt"})
        self.login_id = login["loginId"]
        open_browser(login["authUrl"])
        end = time.monotonic() + 600
        while time.monotonic() < end:
            event = self.next_event(max(0.1, end - time.monotonic()))
            if event.get("method") == "account/login/completed":
                if event["params"].get("loginId") != self.login_id:
                    continue
                if not event["params"].get("success"):
                    raise ProviderError("Вход в ChatGPT не завершён")
                self.login_id = None
                return self.models()
        raise ProviderError("Время входа в ChatGPT истекло")

    def models(self):
        return [model["model"] for model in self.rpc("model/list", {})["data"]]

    def reply(self, system, messages):
        if not self.model:
            raise ProviderError("Выберите модель ChatGPT")
        # Each turn receives the app's bounded conversation; no persisted thread
        # can introduce tools or state from another installer session.
        thread = self.rpc("thread/start", {"model": self.model, "ephemeral": True,
            "sandbox": "read-only", "approvalPolicy": "never", "baseInstructions": system})
        self.thread_id = thread["thread"]["id"]
        turn = self.rpc("turn/start", {"threadId": self.thread_id,
            "input": [{"type": "text", "text": json.dumps(messages, ensure_ascii=False)}],
            "outputSchema": REPLY_SCHEMA})
        turn_id = turn["turn"]["id"]
        text = ""
        end = time.monotonic() + 180
        while time.monotonic() < end:
            event = self.next_event(max(0.1, end - time.monotonic()))
            params = event.get("params", {})
            if params.get("threadId") != self.thread_id:
                continue
            if event.get("method") == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
                text = params["item"].get("text", "")
            if event.get("method") == "turn/completed" and params.get("turn", {}).get("id") == turn_id:
                if params["turn"].get("status") != "completed":
                    raise ProviderError("ChatGPT не завершил ответ")
                self.rpc("thread/unsubscribe", {"threadId": self.thread_id})
                return parse_json_reply(text)
        self.rpc("turn/interrupt", {"threadId": self.thread_id, "turnId": turn_id})
        raise ProviderError("Ответ ChatGPT занял слишком много времени")

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        for pipe in (self.proc.stdin, self.proc.stdout):
            if pipe:
                pipe.close()
