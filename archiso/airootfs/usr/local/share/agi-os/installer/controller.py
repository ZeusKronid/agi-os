"""Conversation state and typed transition to the installation review."""

import json
import threading
import time

from domain import GIB, Configuration, PLANNER_PROMPT, ValidationError, default_system_context, hibernation_swap_size
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
        self.kept = False  # the last reply kept the configuration agreed earlier
        self.lock = threading.Lock()

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
                "driver_notes": graphical["notes"], "preview_cannot_verify": graphical["unverified"],
                "hibernation_swap_file_gib": hibernation_swap_size(hardware["memory"]) // GIB if hardware["memory"] else None}

    def report_check_failure(self, text):
        """The installed preview rejected files the model wrote; the model sees the
        checker output together with the user's next message."""
        note = ("Application note (data): the installer checked the generated configuration files "
                "inside the installed preview and they failed. Fix them in the next configuration:\n" + text)
        if self.history and self.history[-1]["role"] == "user":
            self.history[-1] = {"role": "user", "content": self.history[-1]["content"] + "\n\n" + note}
        else:
            self.history.append({"role": "user", "content": note})

    def respond(self, text, turn=None):
        """One user turn: up to ROUNDS model replies with repository lookups in between.

        The turn works on a copy of the history and commits it at the end, so a turn
        cancelled from the page (turn.cancel) leaves the conversation and the agreed
        configuration exactly as they were. A reply without a configuration (a question,
        an explanation) keeps the configuration agreed earlier: only a new, valid proposal
        replaces it."""
        turn = turn or Turn(lambda text: self.notify("status", text))
        if self.installing:
            raise ValidationError("The configuration can’t change during installation")
        if not text.strip() or len(text) > 16000:
            raise ValidationError("Write a message of up to 16000 characters")
        if sum(len(m["content"]) for m in self.history) > 180000:
            raise ValidationError("The conversation is too long. Note what you agreed on and start a new connection.")
        history = list(self.history)
        if history and history[-1]["role"] == "user":
            # A pending application note (or an unanswered message) stays in the same turn:
            # providers expect alternating roles.
            history[-1] = {"role": "user", "content": history[-1]["content"] + "\n\n" + text}
        else:
            history.append({"role": "user", "content": text})
        system = (PLANNER_PROMPT + "\nAGIOS standard system (data, default_system): "
                  + json.dumps(default_system_context(self.snapshot["firmware"]), ensure_ascii=False)
                  + "\nDetected hardware (data): " + json.dumps(self.hardware_context(), ensure_ascii=False))
        try:
            for round_number in range(1, self.ROUNDS + 1):
                turn.step("Asking the model" + (f" again (round {round_number} of {self.ROUNDS})" if round_number > 1 else ""))
                turn.check()
                # A provider that can stop its request early gets the cancel token.
                reply = (self.provider.reply(system, history, cancel=turn.cancelled)
                         if getattr(self.provider, "cancellable", False) else self.provider.reply(system, history))
                turn.check()
                history.append({"role": "assistant", "content": json.dumps(reply, ensure_ascii=False)})
                if reply["lookup"]:
                    turn.step("Looking up packages: " + ", ".join(reply["lookup"]))
                    found = self.catalog.search(reply["lookup"])
                    history.append({"role": "user", "content": "Repository lookup results (data): " + json.dumps(found)})
                    continue
                config = None
                if reply["configuration"] is not None:
                    turn.step("Checking the proposed configuration")
                    try:
                        config = self.checked(reply["configuration"])
                    except ValidationError as exc:
                        history.append({"role": "user", "content": "Application validation rejected proposal: " + str(exc)})
                        turn.step("The proposal did not pass the checks; asking the model to fix it: " + str(exc))
                        continue
                self.commit(turn, history, config)
                return reply
        except Cancelled:
            raise
        except Exception:
            # Nothing is agreed by a failed turn; the user's message stays for the next one.
            self.commit(turn, history, None, answered=False)
            raise
        self.commit(turn, history, None, answered=False)
        raise ValidationError("The proposal needs more detail. Say what to change; nothing has been written to disk.")

    ROUNDS = 4

    def checked(self, data):
        config = Configuration.parse(data)
        selected_disk(self.snapshot, config.disk)
        if self.snapshot["firmware"] == "bios" and config.bootloader != "grub":
            raise ValidationError("BIOS needs GRUB")
        if config.partition_table == "msdos" and self.snapshot["firmware"] != "bios":
            raise ValidationError("partition_table msdos is only for BIOS computers; this one boots UEFI, use gpt")
        if config.swap == "hibernate":
            hibernation_swap_size(profile(self.snapshot["hardware"])["memory"])
        self.catalog.validate([*config.packages, *config.effective_fonts()])
        return config

    def commit(self, turn, history, config, answered=True):
        """Apply a finished turn unless the page cancelled it first (atomic with cancel)."""
        with self.lock:
            if turn.cancelled.is_set():
                raise Cancelled("The request was cancelled; nothing changed")
            turn.committed = True
            self.history = history
            # "Kept" describes an answer that left the agreement as it was; after an error the
            # page shows the error, not that note.
            self.kept = answered and config is None and self.configuration is not None
            if config is not None:
                self.configuration = config
            self.stage_changed(4 if self.configuration else 2)

    def cancel(self, turn):
        """Cancel a running turn. False if it already finished: its result stands."""
        with self.lock:
            if turn.committed:
                return False
            turn.cancelled.set()
        return True


class Cancelled(Exception):
    """The user cancelled the request on the page; the turn left no trace."""


class Turn:
    """One running request to the model, as the page sees it: its steps and whether it
    was cancelled. Steps of a cancelled turn are not reported any more."""

    def __init__(self, notify=lambda text: None):
        self.cancelled = threading.Event()
        self.committed = False
        self.started = time.time()
        self.steps = []
        self.notify = notify

    def step(self, text):
        if not self.cancelled.is_set():
            self.steps = [*self.steps, {"text": text, "at": round(time.time() - self.started, 1)}]
            self.notify(text)

    def check(self):
        if self.cancelled.is_set():
            raise Cancelled("The request was cancelled; nothing changed")

    def public(self):
        return {"started": self.started, "steps": self.steps[-8:], "cancelled": self.cancelled.is_set()}


class DemoCatalog:
    def validate(self, packages):
        return list(packages)

    def search(self, queries):
        return {query: [] for query in queries}


class DemoProvider:
    model = "Interface demo"

    def close(self):
        pass

    def reply(self, system, messages):
        return {"message": "This is a demo reply without an LLM. I prepared an example system with Sway. "
                "You can open the summary and run a simulation; no real disk is changed.",
                "suggestions": [], "lookup": [], "configuration": {
                    "disk": "/dev/vda", "filesystem": "ext4", "bootloader": "systemd-boot",
                    "hostname": "agi-workstation", "username": "tester", "locale": "ru_RU.UTF-8",
                    "timezone": "Europe/Moscow", "keyboard_layouts": ["us", "ru"],
                    "desktop": "Sway — demo example", "session": "sway",
                    "packages": ["sway", "foot", "firefox", "greetd", "greetd-regreet", "cage"],
                    "services": ["greetd.service"], "home_files": [], "system_files": [], "swap": "zram",
                    "requirements": ["A working Sway session", "Firefox browser", "Russian and English keyboard layouts"],
                    "console_keymap": "", "console_font": "", "fonts": [], "locale_overrides": [], "time_sync": True,
                }}
