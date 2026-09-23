"""Static checks of the Live image profile: no Codex/GTK-era entry points remain."""

import configparser
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "archiso"
AIROOTFS = PROFILE / "airootfs"
APP = AIROOTFS / "usr/local/share/agi-os/installer"
sys.path.insert(0, str(APP))
from chatgpt import ChatGPTProvider


def text_files():
    for path in AIROOTFS.rglob("*"):
        if path.is_file() and not path.is_symlink():
            try:
                yield path, path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue


def packages():
    lines = (PROFILE / "packages.x86_64").read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


class LiveImageTests(unittest.TestCase):
    def test_no_full_access_agent_configuration(self):
        for path, content in text_files():
            self.assertNotIn("danger-full-access", content, path)
        self.assertEqual([p for p in AIROOTFS.rglob(".codex")], [])

    def test_no_terminal_agent_instructions(self):
        self.assertEqual([p for p in AIROOTFS.rglob("AGENTS.md")], [])

    def test_desktop_entries_do_not_start_codex(self):
        entries = list(AIROOTFS.rglob("*.desktop"))
        self.assertTrue(entries)
        for path in entries:
            parser = configparser.ConfigParser(interpolation=None)
            parser.read(path, encoding="utf-8")
            command = parser["Desktop Entry"].get("Exec", "")
            self.assertNotIn("codex", command.lower(), path)
            self.assertNotIn("xfce4-terminal", command, path)

    def test_local_commands_do_not_start_codex(self):
        for path in (AIROOTFS / "usr/local/bin").iterdir():
            self.assertNotIn("codex", path.read_text().lower(), path)

    def test_gtk_installer_is_gone(self):
        self.assertFalse((APP / "app.py").exists())
        self.assertFalse((AIROOTFS / "usr/local/share/agi-os/welcome.html").exists())
        self.assertNotIn("python-gobject", packages())

    def test_chatgpt_backend_packages_remain(self):
        self.assertTrue({"openai-codex", "bubblewrap"} <= packages())


class ChatGPTIsolationTests(unittest.TestCase):
    def test_backend_runs_in_bubblewrap_without_host_home_or_tools(self):
        proc = MagicMock()
        proc.stdout = iter(())
        proc.poll.return_value = None
        with patch("chatgpt.shutil.which", return_value="/usr/bin/tool"), \
             patch("chatgpt.subprocess.Popen", return_value=proc) as popen, \
             patch.object(ChatGPTProvider, "rpc", return_value={}), \
             patch.object(ChatGPTProvider, "send"):
            provider = ChatGPTProvider()
            provider.owner.join(timeout=5)
        args = popen.call_args.args[0]
        self.assertEqual(args[0], "bwrap")
        self.assertIn("--unshare-all", args)
        home = str(Path.home())
        # The home is a new empty directory, never a bind of the Live user's home.
        self.assertEqual(args[args.index("--dir") + 1], home)
        for flag in ("--bind", "--ro-bind"):
            for index, value in enumerate(args):
                if value == flag:
                    self.assertFalse(args[index + 1].startswith(home), args[index + 1])
        codex = args[args.index("codex"):]
        self.assertIn("features.shell_tool=false", codex)
        self.assertIn('cli_auth_credentials_store="ephemeral"', codex)
        self.assertEqual(codex[-3:], ["app-server", "--listen", "stdio://"])
        self.assertEqual(set(popen.call_args.kwargs["env"]) - {"PATH", "HOME", "LANG"}, set())


if __name__ == "__main__":
    unittest.main()
