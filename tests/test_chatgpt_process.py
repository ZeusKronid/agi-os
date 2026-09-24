"""Local app-server lifecycle regression; no account or model inference needed."""

import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
from chatgpt import ChatGPTProvider
from providers import ProviderError


class CloseTests(unittest.TestCase):
    """close() without a real backend: a child that outlives the sandbox keeps the pipe open."""

    def test_close_returns_while_a_descendant_still_holds_stdout(self):
        # sh is the "sandbox"; the background sleep plays a backend that escaped the kill.
        proc = subprocess.Popen(["sh", "-c", "sleep 30 & echo '{\"ready\": true}'; sleep 30"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, bufsize=1, start_new_session=True)
        def reap():
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # the escaped descendant too
            except ProcessLookupError:
                pass
        self.addCleanup(reap)
        provider = ChatGPTProvider.__new__(ChatGPTProvider)
        provider.proc, provider.closed, provider.close_lock = proc, threading.Event(), threading.Lock()
        provider.events = queue.Queue()
        provider.owner = threading.Thread(target=proc.wait, daemon=True)
        provider.reader = threading.Thread(target=provider._reader, daemon=True)
        provider.owner.start()
        provider.reader.start()
        provider.JOIN_TIMEOUT = 0.3
        self.assertEqual(provider.events.get(timeout=10), {"ready": True})  # the descendant is running
        done = threading.Event()
        threading.Thread(target=lambda: (provider.close(), done.set()), daemon=True).start()
        self.assertTrue(done.wait(10), "close() deadlocked on the reader's pipe")
        self.assertIsNotNone(proc.poll())
        self.assertTrue(proc.stdin.closed)
        with self.assertRaises(ProviderError):
            provider.send({"method": "x"})
        provider.close()  # repeatable


# Spawns bubblewrap (user namespaces) and the Codex backend: opt-in, never by default on
# a developer workstation (see the host-safety rules of the test stand).
@unittest.skipUnless(os.environ.get("AGIOS_TEST_BWRAP") == "1" and shutil.which("bwrap") and shutil.which("codex"),
                     "set AGIOS_TEST_BWRAP=1 (needs bubblewrap and Codex)")
class ChatGPTProcessTests(unittest.TestCase):
    def test_backend_survives_connection_worker_and_subsequent_worker_exit(self):
        results = queue.Queue()

        def connect():
            try:
                results.put(ChatGPTProvider())
            except Exception as exc:
                results.put(exc)

        connection = threading.Thread(target=connect)
        connection.start()
        connection.join(timeout=40)
        self.assertFalse(connection.is_alive())
        provider = results.get(timeout=1)
        if isinstance(provider, Exception):
            raise provider
        try:
            self.assertIsNone(provider.proc.poll())

            def next_request():
                try:
                    results.put(provider.rpc("account/read", {}))
                except Exception as exc:
                    results.put(exc)

            request = threading.Thread(target=next_request)
            request.start()
            request.join(timeout=40)
            self.assertFalse(request.is_alive())
            result = results.get(timeout=1)
            if isinstance(result, Exception):
                raise result
            self.assertIsNone(result["account"], "must not import the host account")
            self.assertIsNone(provider.proc.poll())
            self.assertIn("data", provider.rpc("model/list", {}))
        finally:
            provider.close()
        self.assertFalse(provider.owner.is_alive())
        self.assertFalse(provider.reader.is_alive())

    def test_close_after_backend_crash_is_safe_and_repeatable(self):
        provider = ChatGPTProvider()
        provider.proc.kill()
        provider.proc.wait(timeout=5)
        with self.assertRaises(ProviderError):
            provider.models()
        provider.close()
        provider.close()
        self.assertFalse(provider.owner.is_alive())
        self.assertFalse(provider.reader.is_alive())

    def test_failed_initialization_closes_backend(self):
        closed = []
        original = ChatGPTProvider.close

        def close(provider):
            original(provider)
            closed.append(provider)

        with patch.object(ChatGPTProvider, "rpc", side_effect=ProviderError("initialization failed")), \
             patch.object(ChatGPTProvider, "close", close):
            with self.assertRaises(ProviderError):
                ChatGPTProvider()
        self.assertEqual(len(closed), 1)
        self.assertIsNotNone(closed[0].proc.poll())
        self.assertFalse(closed[0].owner.is_alive())


if __name__ == "__main__":
    unittest.main()
