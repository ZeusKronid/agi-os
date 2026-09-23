import contextvars
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'archiso/airootfs/usr/local/share/agi-os/installer'))
import journal
import worker

FAKE_KEY = 'sk-' + 'proj-' + 'FAKE' * 5  # built at runtime: not a real key format for scanners


def parse_native(payload):
    """Decode journald's native datagram format back into a dict."""
    fields, rest = {}, payload
    while rest:
        line, _, tail = rest.partition(b'\n')
        if b'=' in line:
            key, value = line.split(b'=', 1)
            fields[key.decode()] = value.decode()
            rest = tail
        else:
            size = struct.unpack('<Q', tail[:8])[0]
            fields[line.decode()] = tail[8:8 + size].decode()
            rest = tail[8 + size + 1:]
    return fields


class RedactTests(unittest.TestCase):
    def test_secret_named_keys_are_masked_everywhere(self):
        value = {'password': 'hunter2-long', 'passphrase': 'luks-secret', 'api_key': 'x', 'key': 'abc',
                 'nested': [{'refresh_token': 'r'}, {'client_secret': 's'}], 'Authorization': 'Bearer z',
                 'keymap': 'ru', 'username': 'tester', 'passphrase_empty': '', 'encrypted': True}
        masked = journal.redact(value)
        for key in ('password', 'passphrase', 'api_key', 'key', 'Authorization'):
            self.assertEqual(masked[key], journal.MASK)
        self.assertEqual(masked['nested'], [{'refresh_token': '***'}, {'client_secret': '***'}])
        self.assertEqual((masked['keymap'], masked['username'], masked['encrypted']), ('ru', 'tester', True))
        self.assertEqual(value['password'], 'hunter2-long', 'the original must stay untouched')

    def test_secret_formats_in_free_text(self):
        samples = {
            'password=hunter2-long end': 'hunter2-long',
            '{"passphrase": "correct horse"}': 'correct',
            'Authorization: Bearer abcdefghijklmnop': 'abcdefghijklmnop',
            'key ' + FAKE_KEY + ' used': FAKE_KEY,
            'anthropic sk-' + 'ant-api03-FAKEFAKEFAKEFAKE': 'FAKEFAKEFAKEFAKE',
            'gemini AI' + 'za' + 'FAKE' * 9: 'FAKEFAKE',
            'jwt eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4': 'SflKxwRJSMeKKF2QT4',
            'tester:$6$saltsalt$abcdefghijklmnop:19000': 'abcdefghijklmnop',
            'tester:$y$j9T$abcdefghijkl$mnopqrstuvwx:19000': 'mnopqrstuvwx',
            'https://user:s3cr3t@mirror.example/repo': 's3cr3t',
            'api-key: 12345678': '12345678',
        }
        for text, secret in samples.items():
            with self.subTest(text=text):
                self.assertNotIn(secret, journal.redact(text))
                self.assertIn(journal.MASK, journal.redact(text))

    def test_ordinary_text_is_unchanged(self):
        for text in ('Устанавливаю пакеты: xfce4 firefox', 'keymap=ru console font cyr-sun16',
                     'Token budget exhausted', 'sgdisk --new=0:2048:4096 /dev/vda', '/dev/disk/by-label/AGIOS_CACHE'):
            self.assertEqual(journal.redact(text), text)


class LoggerTests(unittest.TestCase):
    def setUp(self):
        self.records = []
        patcher = patch.object(journal, 'sink', self.records.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_record_fields_and_redaction(self):
        journal.Logger('web').warning('build.event', 'password=hunter2-long', stage=3, api_key='sk-x')
        record = self.records[0]
        self.assertEqual(record['SYSLOG_IDENTIFIER'], 'agios-web')
        self.assertEqual((record['PRIORITY'], record['AGIOS_EVENT'], record['AGIOS_COMPONENT']), ('4', 'build.event', 'web'))
        self.assertNotIn('hunter2-long', record['MESSAGE'])
        self.assertEqual(json.loads(record['AGIOS_DATA']), {'stage': 3, 'api_key': '***'})
        self.assertNotIn('AGIOS_OPERATION', record)
        self.assertIn(record['SYSLOG_IDENTIFIER'], journal.IDENTIFIERS)

    def test_operation_follows_the_context(self):
        def run():
            journal.operation.set(journal.new_operation('build'))
            journal.Logger('web').info('a', 'inside')
        contextvars.copy_context().run(run)
        journal.Logger('web').info('b', 'outside')
        self.assertRegex(self.records[0]['AGIOS_OPERATION'], journal.TRACE)
        self.assertNotIn('AGIOS_OPERATION', self.records[1])

    def test_adopt_takes_only_well_formed_trace(self):
        def run(request):
            result = journal.adopt(request)
            return result, journal.operation.get()
        request, trace = contextvars.copy_context().run(run, {'op': 'probe', 'trace': 'build-0123456789ab'})
        self.assertEqual((request, trace), ({'op': 'probe'}, 'build-0123456789ab'))
        request, trace = contextvars.copy_context().run(run, {'op': 'probe', 'trace': 'x\nMESSAGE=forged'})
        self.assertEqual((request, trace), ({'op': 'probe'}, None))

    def test_traceback_is_part_of_the_message(self):
        try:
            raise RuntimeError('boom with password=hunter2-long')
        except RuntimeError as exc:
            journal.Logger('storage').error('op.failed', 'Внутренняя ошибка', exc=exc)
        record = self.records[0]
        self.assertEqual(record['AGIOS_ERROR'], 'RuntimeError')
        self.assertIn('Traceback', record['MESSAGE'])
        self.assertNotIn('hunter2-long', record['MESSAGE'])

    def test_logging_never_raises(self):
        with patch.object(journal, 'sink', side_effect=OSError('journal gone')):
            journal.Logger('web').info('x', 'still fine')
        journal.Logger('web').info('x', 'x' * (journal.MAX_MESSAGE + 10))
        self.assertLess(len(self.records[-1]['MESSAGE']), journal.MAX_MESSAGE + 100)

    def test_runner_logs_commands_without_secret_output(self):
        runner = worker.Runner(journal.Logger('worker'))
        runner.run(['true'])
        with self.assertRaises(Exception):
            runner.run(['sh', '-c', 'cat; exit 3'], input_text='luks-secret-value')
        done, failed = self.records
        self.assertEqual((done['AGIOS_EVENT'], json.loads(done['AGIOS_DATA'])['args']), ('command.done', ['true']))
        self.assertEqual(failed['AGIOS_EVENT'], 'command.failed')
        self.assertNotIn('luks-secret-value', json.dumps(failed))


class NativeProtocolTests(unittest.TestCase):
    def test_datagram_reaches_journal_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'socket')
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server, \
                    patch.object(journal, 'SOCKET', path), patch.object(journal, 'enabled', return_value=True):
                server.bind(path)
                journal.Logger('finalize').info('finalize.event', 'одна строка\nвторая', layout='erase')
                fields = parse_native(server.recv(65536))
        self.assertEqual(fields['MESSAGE'], 'одна строка\nвторая')
        self.assertEqual(fields['SYSLOG_IDENTIFIER'], 'agios-finalize')
        self.assertEqual(json.loads(fields['AGIOS_DATA']), {'layout': 'erase'})

    def test_outside_live_nothing_is_written(self):
        with patch.object(journal, 'enabled', return_value=False), patch.object(journal, '_journal') as send, \
                patch.dict(os.environ, {'AGIOS_LOG_STDERR': ''}):
            journal.Logger('web').info('x', 'y')
        send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
