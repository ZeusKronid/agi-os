"""CI helpers: the smoke boot talks to the real Live instrumentation, pins stay consistent."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('smoke_boot', ROOT / 'scripts/ci/smoke-boot.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeCommandTests(unittest.TestCase):
    def command(self, firmware):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(smoke.subprocess, 'run') as run, \
                patch.object(smoke, 'ovmf', return_value=(os.devnull, os.devnull)):
            command = smoke.qemu_command(Path('/x/live.iso'), firmware, 4096, 2, Path(directory))
        run.assert_called_once()
        return command

    def test_vm_carries_what_the_live_qa_service_requires(self):
        command = ' '.join(self.command('bios'))
        unit = (ROOT / 'archiso/airootfs/etc/systemd/system/agi-qa.service').read_text()
        guest = (ROOT / 'scripts/web/qa-guest.py').read_text()
        marker = re.search(r'ConditionPathExists=/sys/firmware/qemu_fw_cfg/by_name/(\S+)/raw', unit).group(1)
        port = re.search(r"/dev/virtio-ports/([\w.-]+)", guest).group(1)
        self.assertIn(f'name={marker},string=1', command)
        self.assertIn(f'name={port}', command)
        self.assertIn('file=/x/live.iso,media=cdrom', command)
        self.assertNotIn('pflash', command)

    def test_uefi_uses_a_private_copy_of_the_variables(self):
        command = self.command('uefi')
        flash = [arg for arg in command if arg.startswith('if=pflash')]
        self.assertEqual(len(flash), 2)
        self.assertIn('readonly=on', flash[0])
        self.assertTrue(flash[1].endswith('OVMF_VARS.fd'))

    def test_falls_back_to_tcg_without_kvm(self):
        with patch.object(smoke, 'kvm_usable', return_value=False):
            command = self.command('bios')
        self.assertEqual(command[command.index('-accel') + 1], 'tcg')


class FakeGuest(threading.Thread):
    """Plays scripts/web/qa-guest.py on the host side of a unix socket."""

    def __init__(self, path, answers):
        super().__init__(daemon=True)
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(str(path))
        self.server.listen(1)
        self.answers = answers

    def run(self):
        connection, _ = self.server.accept()
        stream = connection.makefile('rb')
        connection.sendall(b'noise from the console\n{"ready":true}\n')
        while line := stream.readline():
            request = json.loads(line)
            key = request['method'] if request['method'] == 'http' else ' '.join(request['args'])
            answer = self.answers.get(key, {'code': 0, 'stdout': '', 'stderr': ''})
            # An unrelated answer first: the client must match answers by id.
            connection.sendall(b'{"id":"other","result":null}\n')
            reply = {'id': request['id'], **({'error': answer['error']} if 'error' in answer else {'result': answer})}
            connection.sendall(json.dumps(reply).encode() + b'\n')
        connection.close()
        self.server.close()


class SmokeCheckTests(unittest.TestCase):
    def run_check(self, answers, revision=''):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        guest = FakeGuest(directory / 'qa.sock', answers)
        guest.start()
        qa = smoke.QA(directory / 'qa.sock')
        self.enterContext(patch.object(smoke, 'POLL', 0.01))
        self.enterContext(patch.object(smoke, 'log'))
        try:
            qa.wait_ready(time.monotonic() + 5)
            return smoke.check(qa, revision, time.monotonic() + 0.2)
        finally:
            qa.close()
            guest.join(5)

    def healthy(self):
        answers = {f'systemctl is-active {unit}': {'code': 0, 'stdout': 'active\n'} for unit in smoke.REQUIRED_UNITS}
        answers['http'] = {'phase': 'idle'}
        answers['cat /usr/local/share/agi-os/source-revision'] = {'code': 0, 'stdout': 'abc123\n'}
        answers['systemctl is-system-running'] = {'code': 0, 'stdout': 'running\n'}
        return answers

    def test_healthy_live_passes(self):
        failures, details = self.run_check(self.healthy(), 'abc123')
        self.assertEqual(failures, [])
        self.assertEqual(details['source_revision'], 'abc123')

    def test_inactive_website_and_wrong_revision_fail(self):
        answers = self.healthy()
        answers['systemctl is-active agi-web.service'] = {'code': 3, 'stdout': 'failed\n'}
        failures, _ = self.run_check(answers, 'other')
        self.assertTrue(any('agi-web.service is failed' in failure for failure in failures))
        self.assertTrue(any('source revision' in failure for failure in failures))

    def test_website_errors_fail_after_the_deadline(self):
        answers = self.healthy()
        answers['http'] = {'error': 'Connection refused'}
        failures, _ = self.run_check(answers)
        self.assertEqual(failures, ['/api/state failed: Connection refused'])


class PinTests(unittest.TestCase):
    def test_snapshot_is_one_archive_day(self):
        snapshot = (ROOT / 'scripts/ci/arch-snapshot').read_text().strip()
        self.assertRegex(snapshot, r'^\d{4}/\d{2}/\d{2}$')

    def test_container_image_is_pinned_by_digest_in_one_version(self):
        pattern = r'archlinux:base-devel-[\d.]+@sha256:[0-9a-f]{64}'
        images = {image for path in ('scripts/ci/build-iso.sh', '.github/workflows/tests.yml')
                  for image in re.findall(pattern, (ROOT / path).read_text())}
        self.assertEqual(len(images), 1, images)

    def test_privileged_build_refuses_to_start_outside_ci(self):
        # Static on purpose: this test must never start the build on a workstation.
        script = (ROOT / 'scripts/ci/build-iso.sh').read_text()
        guard = script.index('${CI:-} != true && ${AGIOS_ALLOW_PRIVILEGED_BUILD:-} != 1')
        self.assertLess(guard, script.index('docker'))
        self.assertLess(guard, script.index('scripts/build-iso.sh --prepare-only'))
        inside = script.index('if [[ ${1:-} == --inside ]]')
        self.assertLess(script.index('/.dockerenv', inside), script.index('pacman', inside))

    def test_third_party_actions_are_pinned_to_commits(self):
        for workflow in (ROOT / '.github/workflows').glob('*.yml'):
            for action in re.findall(r'uses:\s*(\S+)', workflow.read_text()):
                if action.startswith('./'):
                    continue
                self.assertRegex(action, r'@[0-9a-f]{40}$', f'{workflow.name}: {action}')


@unittest.skipUnless(shutil.which('git'), 'git is not installed')
class ChangelogTests(unittest.TestCase):
    def test_lists_commits_since_the_previous_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.invalid',
                   'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@example.invalid'}
            git = lambda *args: subprocess.run(['git', '-c', 'tag.gpgSign=false', '-c', 'commit.gpgSign=false', *args],
                                               cwd=directory, env=env, check=True, capture_output=True)
            git('init', '-q')
            for message, tag in (('First', 'v0.1.0'), ('Second', None), ('Third', 'v0.2.0')):
                git('commit', '-q', '--allow-empty', '-m', message)
                if tag:
                    git('tag', tag)
            info = Path(directory) / 'build-info.json'
            info.write_text(json.dumps({'iso': 'agi-os.iso', 'size': 2**30, 'sha256': 'f' * 64,
                                        'source_revision': 'abc', 'arch_snapshot': '2026/09/20',
                                        'build_image': 'archlinux', 'source_date_epoch': 1}))
            notes = subprocess.run([ROOT / 'scripts/ci/changelog.sh', 'v0.2.0', info], cwd=directory,
                                   check=True, capture_output=True, text=True).stdout
        self.assertIn('## Changes since v0.1.0', notes)
        self.assertIn('- Third', notes)
        self.assertIn('- Second', notes)
        self.assertNotIn('- First', notes)
        self.assertIn('f' * 64, notes)


if __name__ == '__main__':
    unittest.main()
