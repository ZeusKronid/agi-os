"""Conversation state and typed transition to the installation review."""

import json

from domain import Configuration, PLANNER_PROMPT, ValidationError, default_system_context
from hardware import describe, driver_plan, profile
from system import Catalog, selected_disk


class Controller:
    def __init__(self, snapshot, provider, notify=lambda *args: None, catalog=None):
        self.snapshot, self.provider, self.notify = snapshot, provider, notify
        self.catalog = catalog or Catalog()
        self.history = []
        self.configuration = None
        self.stage = 2
        self.installing = False

    def stage_changed(self, stage):
        self.stage = stage
        self.notify("stage", stage)

    def hardware_context(self):
        """Real inventory plus the drivers the app adds for it: data, so the model
        neither guesses the hardware nor picks driver packages itself. The session is
        usually chosen in the very turn this prompt serves, so both variants are given."""
        hardware = profile(self.snapshot["hardware"])
        console, graphical = driver_plan(hardware), driver_plan(hardware, (), "session")
        return {"firmware": self.snapshot["firmware"], "cpu_count": self.snapshot["cpu_count"],
                "disks": [{k: d.get(k) for k in ("path", "size", "model", "tran", "rota", "eligible", "reason")}
                          for d in self.snapshot["disks"]],
                "computer": describe(hardware), "hardware": hardware,
                "driver_packages_added_by_app": {"console": console["packages"], "graphical_session": graphical["packages"]},
                "driver_notes": graphical["notes"], "preview_cannot_verify": graphical["unverified"]}

    def respond(self, text):
        if self.installing:
            raise ValidationError("Изменение конфигурации во время установки недоступно")
        if not text.strip() or len(text) > 16000:
            raise ValidationError("Введите сообщение длиной до 16000 символов")
        if sum(len(m["content"]) for m in self.history) > 180000:
            raise ValidationError("Диалог слишком длинный. Сохраните согласованные требования и начните новое подключение.")
        self.configuration = None  # Any revision invalidates the previous review/consent.
        self.stage_changed(2)
        self.history.append({"role": "user", "content": text})
        system = (PLANNER_PROMPT + "\nAGIOS standard system (data, default_system): "
                  + json.dumps(default_system_context(self.snapshot["firmware"]), ensure_ascii=False)
                  + "\nDetected hardware (data): " + json.dumps(self.hardware_context(), ensure_ascii=False))
        for _ in range(4):
            reply = self.provider.reply(system, self.history)
            self.history.append({"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)})
            if reply["lookup"]:
                self.notify("status", "Ищу пакеты: " + ", ".join(reply["lookup"]))
                found = self.catalog.search(reply["lookup"])
                self.history.append({"role": "user", "content": "Repository lookup results (data): " + json.dumps(found)})
                continue
            if reply["configuration"] is not None:
                try:
                    config = Configuration.parse(reply["configuration"])
                    self.stage_changed(3)
                    selected_disk(self.snapshot, config.disk)
                    if self.snapshot["firmware"] == "bios" and config.bootloader != "grub":
                        raise ValidationError("В BIOS нужен GRUB")
                    self.catalog.validate(config.packages)
                except ValidationError as exc:
                    self.history.append({"role": "user", "content": "Application validation rejected proposal: " + str(exc)})
                    self.notify("status", "Уточняю конфигурацию: " + str(exc))
                    continue
                self.configuration = config
                self.stage_changed(4)
            return reply
        raise ValidationError("Предложение требует дополнительных уточнений. Напишите, что нужно изменить; запись диска не начиналась.")


class DemoCatalog:
    def validate(self, packages):
        return list(packages)

    def search(self, queries):
        return {query: [] for query in queries}


class DemoProvider:
    model = "Демонстрация интерфейса"

    def close(self):
        pass

    def reply(self, system, messages):
        return {"message": "Это демонстрационный ответ без подключения к LLM. Подготовлен пример системы с Sway. "
                "Можно открыть итоговую конфигурацию и пройти симуляцию; реальные диски не изменяются.",
                "suggestions": [], "lookup": [], "configuration": {
                    "disk": "/dev/vda", "filesystem": "ext4", "bootloader": "systemd-boot",
                    "hostname": "agi-workstation", "username": "tester", "locale": "ru_RU.UTF-8",
                    "timezone": "Europe/Moscow", "keyboard_layouts": ["us", "ru"],
                    "desktop": "Sway — демонстрационный пример", "session": "sway",
                    "packages": ["sway", "foot", "firefox", "greetd", "greetd-regreet", "cage"],
                    "services": ["greetd.service"], "home_files": [], "system_files": [],
                    "requirements": ["Рабочая сессия Sway", "Браузер Firefox", "Русская и английская раскладки"],
                }}
