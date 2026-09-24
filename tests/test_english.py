"""The native installer shows engine messages in English."""
import re
import sys
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / "archiso/airootfs/usr/local/share/agi-os/installer"
sys.path.insert(0, str(ENGINE))
from english import english

CYRILLIC = re.compile("[А-Яа-яЁё]")


class EnglishTest(unittest.TestCase):
    def test_every_worker_progress_text_is_translated(self):
        source = (ENGINE / "worker.py").read_text()
        texts = re.findall(r'emit\("(?:progress|installed)", stage=\d, text=(f?"[^"]*"(?: \+ config\.disk)?)\)', source)
        self.assertGreaterEqual(len(texts), 7)
        samples = {
            'f"Повторяю загрузку пакетов (попытка {attempt + 1} из {attempts})…"': "Повторяю загрузку пакетов (попытка 2 из 3)…",
            '"Создаю согласованные разделы на " + config.disk': "Создаю согласованные разделы на /dev/vda",
            'f"Устанавливаю выбранные пакеты ({min(index + BATCH, len(extra))} из {len(extra)})…"': "Устанавливаю выбранные пакеты (24 из 120)…",
            'f"Создаю swap-файл для гибернации ({swap_size // GIB} ГиБ, по объёму RAM)…"': "Создаю swap-файл для гибернации (16 ГиБ, по объёму RAM)…",
        }
        for literal in texts:
            text = samples.get(literal, literal.strip('"'))
            self.assertIsNone(CYRILLIC.search(english(text)), text)

    def test_patterns_keep_details(self):
        self.assertEqual(english("Устанавливаю выбранные пакеты (24 из 120)…"), "Installing your packages (24 of 120)…")
        self.assertEqual(english("Ключ не принят (HTTP 401)"), "Key not accepted (HTTP 401)")
        self.assertEqual(english("Уточняю конфигурацию: Неизвестный часовой пояс"), "Refining the configuration: Unknown time zone")
        self.assertEqual(english("Ищу пакеты: sway, foot"), "Looking up packages: sway, foot")

    def test_unknown_text_passes_through(self):
        self.assertEqual(english("something new"), "something new")


if __name__ == "__main__":
    unittest.main()
