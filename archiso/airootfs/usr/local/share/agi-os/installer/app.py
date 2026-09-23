"""Native GTK installer. Run with --demo to preview without network or disk writes."""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from controller import Controller, DemoCatalog, DemoProvider
from domain import STAGES, ValidationError
from providers import APIProvider, PROVIDERS, ProviderError
from bridge import BridgeProvider, PORT as BRIDGE_PORT
from system import demo_inventory, inventory, selected_disk


HERE = Path(__file__).resolve().parent
CSS = b"""
window { background: #101722; color: #e3eaf3; }
.sidebar { background: #151f2e; padding: 22px; }
.brand { font-size: 26px; font-weight: 800; color: #8ce0c4; }
.title { font-size: 27px; font-weight: 700; }
.muted { color: #9caec4; }
.step { padding: 11px 2px; color: #899bb3; }
.current { color: #8ce0c4; font-weight: 700; }
.complete { color: #d4e5f3; }
.card { background: #1c293a; border-radius: 12px; padding: 18px; }
.warning { color: #ffcc80; }
entry, textview text, textview { background: #182334; color: #edf4ff; }
entry { padding: 10px; border: 1px solid #35455b; border-radius: 7px; }
button { padding: 9px 15px; border-radius: 7px; background: #293a50; color: #edf4ff; border: 0; }
button:hover { background: #354c67; }
button.suggested-action { background: #69d5b2; color: #10241d; font-weight: 700; }
button.destructive-action { background: #ab433d; color: white; }
button:disabled { opacity: 0.4; }
progressbar progress { background: #69d5b2; }
"""


def label(text, css=None):
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_line_wrap(True)
    widget.set_max_width_chars(85)
    if css:
        widget.get_style_context().add_class(css)
    return widget


def button(text, callback, primary=False):
    widget = Gtk.Button(label=text)
    widget.connect("clicked", callback)
    if primary:
        widget.get_style_context().add_class("suggested-action")
    return widget


def open_browser_once(url, is_current=lambda: True):
    def open_url():
        if is_current():
            webbrowser.open(url)
        # webbrowser.open returns True; returning it to GLib would reopen forever.
        return GLib.SOURCE_REMOVE
    GLib.idle_add(open_url)


class InstallerWindow(Gtk.Window):
    def __init__(self, demo=False):
        super().__init__(title="AGI OS — Установка")
        self.demo = demo
        self.provider = None
        self.controller = None
        self.worker = None
        self.installed_received = False
        self.busy = False
        self.connection_generation = 0
        self.connection_lock = threading.Lock()
        self.connect("delete-event", self.on_close)
        monitor = Gdk.Display.get_default().get_monitor(0).get_workarea()
        self.set_default_size(min(1140, monitor.width - 32), min(800, monitor.height - 64))
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_border_width(0)
        style = Gtk.CssProvider()
        style.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(root)
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar.set_size_request(230, -1)
        sidebar.get_style_context().add_class("sidebar")
        sidebar.pack_start(label("AGI OS", "brand"), False, False, 12)
        sidebar.pack_start(label("Ваша система.\nВаш выбор.", "muted"), False, False, 8)
        self.steps = []
        for i, title in enumerate(STAGES, 1):
            item = label(f"{i:02}   {title}", "step")
            sidebar.pack_start(item, False, False, 0)
            self.steps.append(item)
        sidebar.pack_end(label("Установка через диалог", "muted"), False, False, 8)
        root.pack_start(sidebar, False, False, 0)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=24)
        root.pack_start(content, True, True, 0)
        self.banner = label("ПРЕДПРОСМОТР · без LLM и без записи дисков" if demo else
                            "Подключите модель и расскажите, какую систему хотите получить.", "warning" if demo else "muted")
        content.pack_start(self.banner, False, False, 0)
        self.stack = Gtk.Stack()
        content.pack_start(self.stack, True, True, 0)
        self.status = label("Проверяю среду…", "muted")
        content.pack_end(self.status, False, False, 0)
        self.connect_page()
        self.chat_page()
        self.progress_page()
        self.set_stage(1)
        self.show_all()
        self.provider_changed()
        self.background(lambda: demo_inventory() if demo else inventory(), self.inventory_ready)

    def background(self, task, done, failed=None):
        def run():
            try:
                result = task()
            except Exception as exc:
                safe = str(exc) if isinstance(exc, (ProviderError, ValidationError)) else "Операция не завершена. Проверьте подключение и повторите."
                GLib.idle_add(failed or self.show_error, safe)
            else:
                GLib.idle_add(done, result)
        threading.Thread(target=run, daemon=True).start()

    def inventory_ready(self, snapshot):
        self.snapshot = snapshot
        self.connect_button.set_sensitive(True)
        self.status.set_text("Среда готова к подключению LLM")
        if BRIDGE_PORT.exists() and not self.demo:
            self.provider_combo.set_active_id("bridge")
            self.connect_provider()
        if not snapshot["live"] and not self.demo:
            self.banner.set_text("Запуск вне live-системы: диалог доступен, запись дисков отключена.")
            self.banner.get_style_context().add_class("warning")

    def show_error(self, text):
        self.busy = False
        self.status.set_text(text)
        self.send_button.set_sensitive(self.controller is not None)
        self.connect_button.set_sensitive(hasattr(self, "snapshot"))

    def set_stage(self, stage):
        for i, item in enumerate(self.steps, 1):
            context = item.get_style_context()
            context.remove_class("current")
            context.remove_class("complete")
            if i == stage:
                context.add_class("current")
            elif i < stage:
                context.add_class("complete")

    def connect_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.pack_start(label("Начнём с вашей модели", "title"), False, False, 0)
        box.pack_start(label("Войдите в ChatGPT, подключите API своего провайдера или локальную модель. "
                             "Ключи вводятся здесь и не попадают в диалог.", "muted"), False, False, 0)
        self.provider_combo = Gtk.ComboBoxText()
        for key, (name, _, _) in PROVIDERS.items():
            self.provider_combo.append(key, name)
        if BRIDGE_PORT.exists():
            self.provider_combo.append("bridge", "Тестовый мост — модель на хосте")
        self.provider_combo.set_active_id("chatgpt")
        self.provider_combo.connect("changed", lambda *_: self.provider_changed())
        box.pack_start(self.provider_combo, False, False, 0)
        self.endpoint = Gtk.Entry(placeholder_text="Базовый адрес API")
        self.key = Gtk.Entry(placeholder_text="API-ключ", visibility=False)
        self.note = label("", "muted")
        box.pack_start(self.endpoint, False, False, 0)
        box.pack_start(self.key, False, False, 0)
        box.pack_start(self.note, False, False, 0)
        row = Gtk.Box(spacing=10)
        self.connect_button = button("Подключить", self.connect_provider, True)
        self.connect_button.set_sensitive(False)
        row.pack_start(self.connect_button, False, False, 0)
        self.key_link = button("Открыть кабинет провайдера", self.open_provider)
        row.pack_start(self.key_link, False, False, 0)
        box.pack_start(row, False, False, 0)
        box.pack_start(label("Модель", "muted"), False, False, 0)
        self.models = Gtk.ComboBoxText.new_with_entry()
        self.models.get_child().set_placeholder_text("Выберите из списка или введите идентификатор модели")
        box.pack_start(self.models, False, False, 0)
        self.begin_button = button("Перейти к диалогу", self.begin_chat, True)
        self.begin_button.set_sensitive(False)
        box.pack_start(self.begin_button, False, False, 0)
        box.pack_start(label("API-провайдеры могут тарифицировать запросы отдельно от подписки на их чат. "
                             "Для совместимого API нужна поддержка структурированных JSON-ответов.", "muted"), False, False, 4)
        self.stack.add_named(box, "connect")

    def provider_changed(self):
        if not hasattr(self, "endpoint"):
            return
        self.reset_provider()
        kind = self.provider_combo.get_active_id()
        info = PROVIDERS.get(kind, ("Тестовый мост", "", ""))
        self.endpoint.set_text(info[1])
        self.endpoint.set_visible(kind in ("compatible", "ollama"))
        self.key.set_text("")
        self.key.set_visible(kind not in ("chatgpt", "ollama", "bridge"))
        self.key_link.set_visible(bool(info[2]))
        self.models.remove_all()
        self.models.set_sensitive(kind != "bridge")
        self.begin_button.set_sensitive(False)
        self.connect_button.set_sensitive(hasattr(self, "snapshot"))
        self.note.set_text("Тестовый режим: используется вход Codex на хосте." if kind == "bridge" else
                           "Вход откроется в браузере этой live-системы." if kind == "chatgpt" else
                           "Для Ollama на хосте QEMU используйте http://10.0.2.2:11434." if kind == "ollama" else
                           "API-ключ хранится только в памяти до отключения или закрытия приложения.")
        self.connect_button.set_label("Открыть вход в ChatGPT" if kind == "chatgpt" else "Подключить")

    def reset_provider(self):
        with self.connection_lock:
            self.connection_generation += 1
            provider, self.provider = self.provider, None
            generation = self.connection_generation
        if provider:
            provider.close()
        return generation

    def open_provider(self, *_):
        url = PROVIDERS.get(self.provider_combo.get_active_id(), ("", "", ""))[2]
        if url:
            webbrowser.open(url)

    def connect_provider(self, *_):
        generation = self.reset_provider()
        kind = self.provider_combo.get_active_id()
        endpoint, key = self.endpoint.get_text(), self.key.get_text()
        self.key.set_text("")
        self.connect_button.set_sensitive(False)
        self.begin_button.set_sensitive(False)
        self.status.set_text("Ожидаю вход в браузере…" if kind == "chatgpt" else "Проверяю подключение…")

        def connect():
            if self.demo:
                return DemoProvider(), ["Демонстрация интерфейса"]
            if kind == "chatgpt":
                from chatgpt import ChatGPTProvider
                provider = ChatGPTProvider()
                with self.connection_lock:
                    current = generation == self.connection_generation
                    if current:
                        self.provider = provider
                if not current:
                    provider.close()
                    raise ProviderError("Подключение отменено")
                try:
                    return provider, provider.login(lambda url: open_browser_once(
                        url, lambda: generation == self.connection_generation))
                except Exception:
                    provider.close()
                    raise
            provider = BridgeProvider() if kind == "bridge" else APIProvider(kind, endpoint, key)
            try:
                return provider, provider.models()
            except Exception:
                provider.close()
                raise

        def done(result):
            provider, models = result
            if generation != self.connection_generation:
                provider.close()
                return
            self.provider = provider
            self.models.remove_all()
            for model in models:
                self.models.append_text(model)
            if models and (self.demo or kind == "bridge"):
                self.models.set_active(0)
            self.begin_button.set_sensitive(True)
            self.connect_button.set_sensitive(True)
            self.status.set_text("Подключено. Выберите модель для диалога.")
            if models and kind == "bridge":
                self.banner.set_text("Тестовый режим: LLM на хосте, авторизация через Codex.")
                self.begin_chat()

        def failed(text):
            if generation == self.connection_generation:
                self.show_error(text)
        self.background(connect, done, failed)

    def begin_chat(self, *_):
        if not self.provider:
            return
        model = self.models.get_child().get_text().strip()
        if not model:
            self.show_error("Выберите модель или введите её идентификатор")
            return
        self.provider.model = model
        self.controller = Controller(self.snapshot, self.provider,
            lambda kind, value: GLib.idle_add(self.controller_event, kind, value),
            DemoCatalog() if self.demo else None)
        self.set_stage(2)
        self.stack.set_visible_child_name("chat")
        self.status.set_text("Подключено: " + model)
        self.add_message("Установщик", "Какую систему вы хотите получить? Расскажите о задачах и предпочтениях. "
                         "Можно назвать любое окружение или оконный менеджер, выбрать систему без графики "
                         "либо попросить подобрать варианты.")
        self.message.grab_focus()

    def controller_event(self, kind, value):
        if kind == "stage":
            self.set_stage(value)
        else:
            self.status.set_text(value)

    def chat_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.pack_start(label("Соберём вашу систему", "title"), False, False, 0)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.messages = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.scroller.add(self.messages)
        box.pack_start(self.scroller, True, True, 0)
        self.suggestions = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE)
        box.pack_start(self.suggestions, False, False, 0)
        self.message = Gtk.Entry(placeholder_text="Опишите пожелания или предложите свой вариант…")
        self.message.connect("activate", self.send_message)
        box.pack_start(self.message, False, False, 0)
        row = Gtk.Box(spacing=10)
        self.send_button = button("Отправить", self.send_message, True)
        row.pack_start(self.send_button, False, False, 0)
        self.review_button = button("Проверить и установить", self.review)
        self.review_button.set_sensitive(False)
        row.pack_start(self.review_button, False, False, 0)
        row.pack_end(button("Сменить провайдера", self.disconnect), False, False, 0)
        box.pack_start(row, False, False, 0)
        self.stack.add_named(box, "chat")

    def add_message(self, author, text):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        card.get_style_context().add_class("card")
        card.pack_start(label(author, "muted"), False, False, 0)
        card.pack_start(label(text), False, False, 0)
        self.messages.pack_start(card, False, False, 0)
        card.show_all()
        def scroll():
            adj = self.scroller.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
            return False
        GLib.timeout_add(80, scroll)

    def send_message(self, *_):
        if self.busy or not self.controller:
            return
        text = self.message.get_text().strip()
        if not text:
            return
        self.busy = True
        self.review_button.set_sensitive(False)
        self.send_button.set_sensitive(False)
        self.message.set_text("")
        self.add_message("Вы", text)
        self.status.set_text("Модель обдумывает запрос…")
        for child in self.suggestions.get_children():
            child.destroy()
        controller = self.controller

        def done(reply):
            if self.controller is not controller:
                return
            self.busy = False
            self.add_message("Помощник", reply["message"])
            for suggestion in reply["suggestions"]:
                self.suggestions.add(button(suggestion, lambda _, s=suggestion: self.choose_suggestion(s)))
            self.suggestions.show_all()
            self.send_button.set_sensitive(True)
            self.review_button.set_sensitive(controller.configuration is not None)
            self.status.set_text("Конфигурация готова к проверке" if controller.configuration else "Ваш вариант можно написать в поле сообщения")

        def failed(text):
            if self.controller is controller:
                self.show_error(text)
        self.background(lambda: controller.respond(text), done, failed)

    def choose_suggestion(self, text):
        self.message.set_text(text)
        self.send_message()

    def disconnect(self, *_):
        if self.busy:
            self.status.set_text("Дождитесь текущего ответа перед сменой провайдера")
            return
        self.reset_provider()
        self.controller = None
        for child in self.messages.get_children():
            child.destroy()
        self.stack.set_visible_child_name("connect")
        self.begin_button.set_sensitive(False)
        self.set_stage(1)

    def review(self, *_):
        if self.busy or not self.controller or not self.controller.configuration:
            return
        config = self.controller.configuration
        disk = selected_disk(self.snapshot, config.disk)
        dialog = Gtk.Dialog(title="Подтверждение установки", transient_for=self, modal=True)
        dialog.set_default_size(780, 680)
        dialog.add_button("Вернуться к диалогу", Gtk.ResponseType.CANCEL)
        confirm = dialog.add_button("Симулировать установку" if self.demo else "Стереть диск и установить", Gtk.ResponseType.OK)
        confirm.get_style_context().add_class("destructive-action")
        confirm.set_sensitive(False)
        area = dialog.get_content_area()
        area.set_spacing(10)
        area.set_border_width(16)
        scroll = Gtk.ScrolledWindow()
        scroll.add(label(config.summary(disk, self.snapshot.get("hardware"))))
        area.pack_start(scroll, True, True, 0)
        consent = Gtk.CheckButton(label="Подтверждаю удаление всех данных именно на " + config.disk)
        area.pack_start(consent, False, False, 0)
        password = Gtk.Entry(visibility=False, placeholder_text="Пароль нового пользователя (от 8 символов)")
        repeat = Gtk.Entry(visibility=False, placeholder_text="Повторите пароль")
        if self.demo:
            password.set_text("demo-password")
            repeat.set_text("demo-password")
        area.pack_start(password, False, False, 0)
        area.pack_start(repeat, False, False, 0)
        area.pack_start(label("Пароль передаётся только локальному установщику и не отправляется модели.", "muted"), False, False, 0)

        def validate(*_):
            value = password.get_text()
            confirm.set_sensitive(consent.get_active() and 8 <= len(value) <= 256
                                  and value == repeat.get_text() and not any(c in value for c in "\r\n\x00")
                                  and (self.demo or self.snapshot["live"]))
        consent.connect("toggled", validate)
        password.connect("changed", validate)
        repeat.connect("changed", validate)
        dialog.show_all()
        response = dialog.run()
        secret = password.get_text() if response == Gtk.ResponseType.OK else ""
        password.set_text("")
        repeat.set_text("")
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.start_install(config, disk, secret)

    def progress_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.pack_start(label("Установка вашей системы", "title"), False, False, 0)
        self.progress_text = label("", "card")
        box.pack_start(self.progress_text, False, False, 0)
        self.progress = Gtk.ProgressBar()
        box.pack_start(self.progress, False, False, 0)
        self.progress_log = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.progress_log)
        box.pack_start(scroll, True, True, 0)
        self.cancel_button = button("Остановить установку", self.cancel_install)
        box.pack_start(self.cancel_button, False, False, 0)
        self.shutdown_button = button("Выключить и отключить установочный ISO", self.shutdown, True)
        self.shutdown_button.set_sensitive(False)
        box.pack_start(self.shutdown_button, False, False, 0)
        self.stack.add_named(box, "progress")

    def start_install(self, config, disk, password):
        self.controller.installing = True
        self.stack.set_visible_child_name("progress")
        self.set_stage(4)
        self.progress_text.set_text("Проверяю конфигурацию и пакеты перед записью…")
        GLib.timeout_add(150, self.pulse)
        if self.demo:
            password = ""
            def simulate():
                for stage, text in ((5, "ДЕМОНСТРАЦИЯ: установка пакетов"), (6, "ДЕМОНСТРАЦИЯ: настройка системы"),
                                    (7, "ДЕМОНСТРАЦИЯ завершена. Реальная система не устанавливалась.")):
                    time.sleep(0.7)
                    GLib.idle_add(self.worker_event, {"kind": "progress", "stage": stage, "text": text})
                return 0
            self.background(simulate, self.worker_done)
            return
        if not self.snapshot["live"]:
            self.worker_event({"kind": "error", "text": "Запись дисков доступна только в live-системе"})
            return
        request = {"configuration": config.as_dict(), "fingerprint": disk["fingerprint"],
                   "consent_digest": config.digest(), "password": password}
        password = ""
        try:
            self.worker = subprocess.Popen(["sudo", "-n", "--", "/usr/bin/python", "-E", "-s", str(HERE / "worker.py")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
            self.worker.stdin.write(json.dumps(request) + "\n")
            self.worker.stdin.flush()
        except OSError:
            self.worker_event({"kind": "error", "text": "Не удалось запустить установочный движок"})
            return
        finally:
            request.pop("password", None)

        def read_worker():
            for line in self.worker.stdout:
                try:
                    GLib.idle_add(self.worker_event, json.loads(line))
                except ValueError:
                    continue
            return self.worker.wait()
        self.background(read_worker, self.worker_done)

    def pulse(self):
        if self.controller and self.controller.installing:
            self.progress.pulse()
            return True
        return False

    def worker_event(self, event):
        text = event.get("text", "")
        self.progress_text.set_text(text)
        buffer = self.progress_log.get_buffer()
        buffer.insert(buffer.get_end_iter(), text + "\n\n")
        if "stage" in event:
            self.set_stage(event["stage"])
        if event["kind"] == "installed":
            self.installed_received = True
            self.progress_text.set_text(text + "\n\nВыключите VM, отключите ISO и загрузитесь с диска. "
                "Проверка доступна через agi-os-verify --gui или agi-os-verify в консоли. "
                "В окружениях с XDG autostart она откроется после входа.")
        elif event["kind"] == "error":
            self.controller.installing = False
            self.cancel_button.set_sensitive(False)
            self.status.set_text("Установка не завершена. Состояние диска требует проверки перед повтором.")

    def worker_done(self, code):
        if not self.demo and not self.installed_received:
            code = 1
        self.controller.installing = False
        self.cancel_button.set_sensitive(False)
        self.progress.set_fraction(1 if code == 0 else 0)
        self.status.set_text("Демонстрация завершена" if self.demo else
                             "Запись завершена; первый запуск ожидает проверки" if code == 0 else "Установка прервана")
        self.shutdown_button.set_sensitive(code == 0 and not self.demo and self.installed_received)
        if self.worker:
            self.worker.stdin.close()
            self.worker.stdout.close()

    def cancel_install(self, *_):
        if self.worker and self.worker.poll() is None:
            self.worker.stdin.write('{"cancel": true}\n')
            self.worker.stdin.flush()
            self.cancel_button.set_sensitive(False)
            self.status.set_text("Останавливаю текущую операцию и отключаю разделы…")

    def shutdown(self, *_):
        if not self.demo and not (self.controller and self.controller.installing):
            subprocess.Popen(["systemctl", "poweroff"])

    def on_close(self, *_):
        if self.controller and self.controller.installing:
            self.status.set_text("Сначала остановите установку кнопкой и дождитесь отключения разделов.")
            return True
        self.reset_provider()
        Gtk.main_quit()
        return False


def main():
    parser = argparse.ArgumentParser(description="AGI OS Installer")
    parser.add_argument("--demo", action="store_true", help="UI preview with fake data; no network or disk operations")
    args = parser.parse_args()
    InstallerWindow(demo=args.demo)
    Gtk.main()


if __name__ == "__main__":
    main()
