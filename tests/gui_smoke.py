"""Exercise GTK with the explicit demo backend; no LLM or disk writes."""
import sys
import time
import threading
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
from app import InstallerWindow, Gtk, Gdk, GLib, open_browser_once

window = InstallerWindow(demo=True)
phase = 0
started = time.monotonic()
screens = Path("/tmp/agi-os-ui")
screens.mkdir(exist_ok=True)
failed = False
browser_patch = patch('app.webbrowser.open', return_value=True)
browser = browser_patch.start()
open_browser_once('https://example.invalid/login')
open_browser_once('https://example.invalid/cancelled-login', lambda: False)


class WaitingProvider:
    def __init__(self):
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def login(self, callback):
        self.started.set()
        self.cancelled.wait(10)
        return ["unused"]

    def close(self):
        self.cancelled.set()


waiting = WaitingProvider()
provider_patch = patch('chatgpt.ChatGPTProvider', return_value=waiting)
provider_patch.start()


def screenshot(name):
    w, h = window.get_size()
    image = Gdk.pixbuf_get_from_window(window.get_window(), 0, 0, w, h)
    image.savev(str(screens / name), "png", [], [])


def advance():
    global phase, failed
    try:
        if time.monotonic() - started > 40:
            raise AssertionError(f"GTK smoke timeout at phase {phase}")
        if phase == 0 and hasattr(window, "snapshot"):
            assert browser.call_count == 1, 'Login URL must open once, even when webbrowser returns True'
            screenshot("connect.png")
            window.demo = False
            window.connect_provider()
            phase = 0.5
        elif phase == 0.5 and waiting.started.is_set():
            assert not window.connect_button.get_sensitive()
            window.select_provider("ollama")
            assert waiting.cancelled.is_set(), 'Switching provider must close pending sign-in'
            assert window.connect_button.get_sensitive(), 'New provider must be connectable'
            window.demo = True
            window.connect_provider()
            phase = 1
        elif phase == 1 and window.begin_button.get_sensitive():
            window.begin_chat()
            window.message.set_text("I want Sway and Firefox with a US keyboard")
            window.send_message()
            phase = 2
        elif phase == 2 and window.review_button.get_sensitive():
            assert window.controller.stage == 4
            assert not window.controller.installing
            screenshot("conversation.png")
            window.review()
            assert window.sheet_revealer.get_reveal_child()
            window.password.set_text("short")
            assert not window.hold.get_sensitive(), 'Erasing needs a valid password'
            window.password.set_text("demo-password")
            window.repeat.set_text("demo-password")
            assert window.hold.get_sensitive()
            phase = 3
            window.hold.on_done()
        elif phase == 3 and window.step in ("install", "done") and not window.controller.installing:
            assert window.worker is None
            assert not window.shutdown_button.get_sensitive()
            assert not window.sheet_revealer.get_reveal_child()
            screenshot("simulation.png")
            print("GTK smoke: provider selection, conversation, review, simulated install passed")
            Gtk.main_quit()
            return False
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        failed = True
        Gtk.main_quit()
        return False
    return True


GLib.timeout_add(150, advance)
Gtk.main()
browser_patch.stop()
provider_patch.stop()
sys.exit(1 if failed else 0)
