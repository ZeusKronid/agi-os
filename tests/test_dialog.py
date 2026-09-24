"""The conversation turn (CMP-129): visible steps, cancellation without a trace, and a
configuration agreed earlier that a question or an explanation does not reset."""
import json
import os
from pathlib import Path
import pty
import queue
import sys
import threading
import time
import tty
import unittest
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
from bridge import BridgeProvider
from chatgpt import ChatGPTProvider
from controller import Cancelled, Controller, DemoCatalog, DemoProvider, Turn
from domain import ValidationError
from providers import ProviderError
from system import demo_inventory


def proposal():
    return DemoProvider().reply("", [])


def answer(text="A question back to you", lookup=()):
    return {"message": text, "suggestions": [], "lookup": list(lookup), "configuration": None}


class Scripted:
    """A provider that answers from a list and records what it saw."""

    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []

    def reply(self, system, messages):
        self.seen.append(list(messages))
        return self.replies.pop(0)


class TurnTests(unittest.TestCase):
    def controller(self, *replies):
        return Controller(demo_inventory(), Scripted(*replies), catalog=DemoCatalog())

    def test_question_after_agreement_keeps_the_configuration(self):
        controller = self.controller(proposal(), answer("Which browser do you prefer?"))
        controller.respond("Sway, please")
        agreed = controller.configuration
        self.assertFalse(controller.kept)
        controller.respond("Can you add a browser?")
        self.assertEqual(controller.configuration, agreed)
        self.assertTrue(controller.kept)
        self.assertEqual(controller.stage, 4)

    def test_new_proposal_replaces_the_configuration(self):
        changed = proposal()
        changed["configuration"]["hostname"] = "renamed"
        controller = self.controller(proposal(), changed)
        controller.respond("Sway, please")
        controller.respond("Call the computer renamed")
        self.assertEqual(controller.configuration.hostname, "renamed")
        self.assertFalse(controller.kept)

    def test_rejected_proposal_keeps_the_agreed_one(self):
        broken = proposal()
        broken["configuration"]["disk"] = "/dev/does-not-exist"
        controller = self.controller(proposal(), broken, answer("That disk does not exist; which one?"))
        controller.respond("Sway, please")
        agreed = controller.configuration
        controller.respond("Use another disk")
        self.assertEqual(controller.configuration, agreed)
        self.assertTrue(any("Application validation rejected" in m["content"] for m in controller.history))

    def test_steps_are_reported_in_order(self):
        seen = []
        controller = self.controller(answer(lookup=["sway"]), proposal())
        turn = Turn(seen.append)
        controller.respond("Sway, please", turn)
        texts = [step["text"] for step in turn.steps]
        self.assertEqual(texts, ["Asking the model", "Looking up packages: sway", "Asking the model again (round 2 of 4)",
                                 "Checking the proposed configuration"])
        self.assertEqual(seen, texts)
        self.assertTrue(all(step["at"] >= 0 for step in turn.steps))

    def test_cancelled_turn_leaves_no_trace(self):
        controller = self.controller(proposal())
        controller.respond("Sway, please")
        history, agreed = list(controller.history), controller.configuration
        started, release = threading.Event(), threading.Event()

        class Slow:
            def reply(self, system, messages):
                started.set()
                release.wait(5)
                changed = proposal()
                changed["configuration"]["hostname"] = "late"
                return changed

        controller.provider = Slow()
        turn, errors = Turn(), []
        worker = threading.Thread(target=lambda: errors.append(self.capture(controller.respond, "Rename it", turn)))
        worker.start()
        self.assertTrue(started.wait(5))
        self.assertTrue(controller.cancel(turn))
        release.set()
        worker.join(5)
        self.assertIsInstance(errors[0], Cancelled)
        self.assertEqual(controller.history, history)
        self.assertEqual(controller.configuration, agreed)
        self.assertTrue(turn.public()["cancelled"])

    def test_cancel_after_the_answer_does_not_undo_it(self):
        controller = self.controller(proposal())
        turn = Turn()
        controller.respond("Sway, please", turn)
        self.assertFalse(controller.cancel(turn))
        self.assertIsNotNone(controller.configuration)

    def test_cancellable_provider_receives_the_token(self):
        tokens = []

        class Interruptible:
            cancellable = True

            def reply(self, system, messages, cancel=None):
                tokens.append(cancel)
                return answer()

        controller = Controller(demo_inventory(), Interruptible(), catalog=DemoCatalog())
        turn = Turn()
        controller.respond("hello", turn)
        self.assertIs(tokens[0], turn.cancelled)

    def test_provider_error_after_cancel_counts_as_cancelled(self):
        turn = Turn()

        class Interrupted:
            cancellable = True

            def reply(self, system, messages, cancel=None):
                turn.cancelled.set()
                raise ProviderError("The request to ChatGPT was cancelled")

        controller = Controller(demo_inventory(), Interrupted(), catalog=DemoCatalog())
        with self.assertRaises(Cancelled):
            controller.respond("hello", turn)
        self.assertEqual(controller.history, [])

    def test_too_many_rounds_still_keeps_the_agreed_configuration(self):
        controller = self.controller(proposal(), *[answer(lookup=["x"])] * 4)
        controller.respond("Sway, please")
        agreed = controller.configuration
        with self.assertRaises(ValidationError):
            controller.respond("Search a lot")
        self.assertEqual(controller.configuration, agreed)

    @staticmethod
    def capture(function, *args):
        try:
            function(*args)
        except Exception as exc:
            return exc
        return None


class HelpToChooseTests(unittest.TestCase):
    """CMP-128: ordinary users get a recommendation, not a questionnaire of components."""

    def test_prompt_recommends_for_a_purpose_and_keeps_an_agreement(self):
        from domain import PLANNER_PROMPT
        for phrase in ("Recommend ONE concrete, complete system", "help choose", "Choose the technical details yourself",
                       "never\nquestions", "An agreed configuration stays in effect"):
            self.assertIn(phrase, PLANNER_PROMPT)

    def test_page_offers_purposes_and_help(self):
        page = (Path(__file__).resolve().parents[1] / "web/static/index.html").read_text()
        for chip in ("Help me choose", "Everyday use", "A setup for development", "Media and games", "Light and fast", "Choose for me"):
            self.assertIn(f">{chip}</button>", page)


class ProgressTests(unittest.TestCase):
    def test_runner_hands_over_output_while_the_command_runs(self):
        import worker
        chunks = []
        output = worker.Runner().run(["sh", "-c", "printf '10%%\\r'; sleep .2; printf '55%%\\r'"], progress=chunks.append)
        self.assertEqual("".join(chunks), "10%\r55%\r")
        self.assertTrue(output.endswith("55%\r"))
        with self.assertRaises(ValidationError):
            worker.Runner().run(["sh", "-c", "echo broken; exit 3"], progress=chunks.append)

    def test_cancel_stops_a_streaming_command(self):
        import worker
        runner = worker.Runner()
        threading.Timer(.3, runner.cancel.set).start()
        started = time.monotonic()
        with self.assertRaises(worker.Cancelled):
            runner.run(["sleep", "30"], progress=lambda text: None)
        self.assertLess(time.monotonic() - started, 10)


class ChatGPTCancelTests(unittest.TestCase):
    def test_cancel_interrupts_the_running_turn(self):
        provider = ChatGPTProvider.__new__(ChatGPTProvider)  # no app-server process
        provider.model, provider.events, provider.token_source = "model", queue.Queue(), None
        provider.turn_lock, provider.thread_id = threading.Lock(), None
        calls = []

        def rpc(method, params, timeout=30):
            calls.append((method, params))
            return {"thread/start": {"thread": {"id": "thread"}}, "turn/start": {"turn": {"id": "turn"}}}.get(method, {})

        provider.rpc = rpc
        provider.events.put({"method": "item/started", "params": {"threadId": "thread"}})
        cancel = threading.Event()
        threading.Timer(.3, cancel.set).start()
        started = time.monotonic()
        with self.assertRaises(ProviderError):
            provider.reply("system", [{"role": "user", "content": "hi"}], cancel=cancel)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(calls[-1], ("turn/interrupt", {"threadId": "thread", "turnId": "turn"}))


class BridgeCancelTests(unittest.TestCase):
    def test_cancel_stops_waiting_and_a_late_answer_is_ignored(self):
        master, slave = pty.openpty()
        tty.setraw(slave)
        provider = BridgeProvider(os.ttyname(slave))
        cancel = threading.Event()
        threading.Timer(.3, cancel.set).start()
        started = time.monotonic()
        try:
            with self.assertRaises(ProviderError) as error:
                provider.reply("system", [{"role": "user", "content": "hi"}], cancel=cancel)
            self.assertIn("cancelled", str(error.exception))
            self.assertLess(time.monotonic() - started, 5)
            # The host answers the cancelled request late; the next request ignores it by id.
            data = b""
            while not data.endswith(b"\n"):
                data += os.read(master, 65536)
            stale = json.loads(data)["id"]

            def host():
                request = b""
                while not request.endswith(b"\n"):
                    request += os.read(master, 65536)
                current = json.loads(request)["id"]
                os.write(master, (json.dumps({"id": stale, "result": ["stale"]}) + "\n"
                                  + json.dumps({"id": current, "result": ["test-model"]}) + "\n").encode())

            thread = threading.Thread(target=host, daemon=True)
            thread.start()
            self.assertEqual(provider.models(), ["test-model"])
            thread.join(5)
        finally:
            provider.close()
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    unittest.main()
