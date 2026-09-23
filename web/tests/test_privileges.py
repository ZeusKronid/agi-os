"""Live privileges: only the website's system user reaches root, and only through
the exact commands the website runs; no Live account can log in with a password."""
import asyncio
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from system import Catalog

REPO = Path(__file__).resolve().parents[2]
ETC = REPO / 'archiso/airootfs/etc'
BUNDLE = Path('/usr/local/share/agi-os')  # SOURCE_ROOT inside the Live image.


def sudoers():
    """Rules of the Live sudoers drop-in as {user: set of allowed command lines}."""
    text = (ETC / 'sudoers.d/10-agi-live').read_text().replace('\\\n', ' ')
    aliases, rules = {}, {}
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line or line.startswith('Defaults'):
            continue
        if line.startswith('Cmnd_Alias'):
            name, commands = line[len('Cmnd_Alias'):].split('=', 1)
            aliases[name.strip()] = {' '.join(c.split()) for c in commands.split(',')}
            continue
        user, rest = line.split(None, 1)
        commands = rest.split('NOPASSWD:', 1)[1] if 'NOPASSWD:' in rest else rest.split(')', 1)[1]
        allowed = rules.setdefault(user, set())
        for command in (c.strip() for c in commands.split(',')):
            allowed |= aliases.get(command, {command})
    return rules


class Process:
    returncode = 0

    async def communicate(self, data):
        return b'{"result": {}}', b''

    async def wait(self):
        return 0


class SudoersTests(unittest.TestCase):
    def test_only_the_site_user_has_rules_and_never_all_commands(self):
        rules = sudoers()
        self.assertEqual(set(rules), {'agi-web'})
        for command in rules['agi-web']:
            self.assertTrue(command.startswith('/usr/bin/'), command)
            self.assertNotIn('ALL', command.split())
        self.assertNotIn('NOPASSWD: ALL', (ETC / 'sudoers.d/10-agi-live').read_text())

    @unittest.skipUnless(shutil.which('visudo'), 'visudo is not installed')
    def test_visudo_accepts_the_drop_in(self):
        result = subprocess.run(['visudo', '-cf', str(ETC / 'sudoers.d/10-agi-live')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def assert_allowed(self, argv):
        self.assertEqual(argv[:2], ('sudo', '-n'))
        self.assertIn(' '.join(argv[2:]), sudoers()['agi-web'])

    def test_root_helpers_match_the_rules(self):
        calls = []

        async def spawn(*argv, **kwargs):
            calls.append(argv)
            return Process()
        with patch.object(server, 'ROOT', BUNDLE), patch('asyncio.create_subprocess_exec', spawn):
            asyncio.run(server.privileged('storage_worker.py', {'op': 'probe'}))
        self.assert_allowed(calls[0])
        # finalize_task builds its own command line; stop it right after the spawn.
        state = type('S', (), {})()
        state.final, state.status, state.phase = {}, '', ''
        state.persist = lambda: None
        state.controller = type('C', (), {'installing': True})()

        async def refuse(*argv, **kwargs):
            calls.append(argv)
            raise OSError('stop')
        with patch.object(server, 'ROOT', BUNDLE), patch('asyncio.create_subprocess_exec', refuse):
            asyncio.run(server.finalize_task(state, {'target': '/dev/vda', 'layout': 'erase'}))
        self.assert_allowed(calls[1])
        self.assertEqual(state.final['phase'], 'error')

    def test_power_and_catalog_match_the_rules(self):
        calls = []

        async def spawn(*argv, **kwargs):
            calls.append(argv)
            return Process()

        class Request:
            def __init__(self, action):
                self.app = {'state': type('S', (), {'final': {'phase': 'complete'},
                                                    'controller': type('C', (), {'installing': False})()})()}
                self.action = action

            async def json(self):
                return {'action': self.action}
        with patch.object(server, 'live_environment', return_value=True), patch('asyncio.create_subprocess_exec', spawn):
            for action in ('poweroff', 'reboot'):
                asyncio.run(server.power(Request(action)))
        for argv in calls:
            self.assert_allowed(argv)
        with patch('system.live_environment', return_value=True), patch('system.Path.is_file', return_value=False), \
                patch('system.read_command', side_effect=['', 'core python 3.14\n']) as read:
            Catalog().load()
        self.assert_allowed(tuple(read.call_args_list[0].args[0]))

    def test_test_mirror_read_matches_the_rule(self):
        source = (REPO / 'web/runtime.py').read_text()
        self.assertIn("['sudo', '-n', '/usr/bin/cat', str(mirror)]", source)
        self.assertIn('/usr/bin/cat /sys/firmware/qemu_fw_cfg/by_name/opt/org.agi-os.test-mirror/raw', sudoers()['agi-web'])


class AccountTests(unittest.TestCase):
    def table(self, name):
        return [line.split(':') for line in (ETC / name).read_text().splitlines() if line.strip()]

    def test_every_password_is_locked(self):
        for fields in self.table('shadow'):
            self.assertTrue(fields[1].startswith(('!', '*')), fields[0])

    def test_site_user_is_a_system_account_and_desktop_user_is_not_admin(self):
        users = {f[0]: f for f in self.table('passwd')}
        self.assertEqual(users['agi-web'][6], '/usr/bin/nologin')
        self.assertLess(int(users['agi-web'][2]), 1000)
        groups = {f[0]: f[3].split(',') if f[3] else [] for f in self.table('group')}
        self.assertEqual(groups['wheel'], [])
        self.assertEqual(groups['autologin'], ['agi'])
        self.assertIn('agi-web', groups)

    def test_no_console_autologin_as_root(self):
        self.assertFalse((ETC / 'systemd/system/getty@tty1.service.d/autologin.conf').exists())
        for path in (ETC / 'systemd').rglob('*.conf'):
            self.assertNotIn('--autologin root', path.read_text(), path)

    def test_services_run_as_the_site_user(self):
        units = ETC / 'systemd/system'
        for unit in ('agi-web.service', 'agi-guacd.service'):
            text = units.joinpath(unit).read_text()
            self.assertIn('User=agi-web\n', text)
            self.assertNotIn('/home/agi', text)
        self.assertIn('StateDirectoryMode=0700', units.joinpath('agi-web.service').read_text())
        qa = units.joinpath('agi-qa.service').read_text()
        # Root only on test stands: the unit requires the hypervisor's test marker.
        self.assertIn('ConditionPathExists=/sys/firmware/qemu_fw_cfg/by_name/opt/org.agi-os.test/raw', qa)
        self.assertIn('GROUP="agi-web"', (ETC / 'udev/rules.d/71-agi-dev-bridge.rules').read_text())


class StorageOwnerTests(unittest.TestCase):
    def test_preview_image_belongs_to_the_calling_site_user(self):
        import storage_worker
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict('os.environ', {'SUDO_UID': '960', 'SUDO_GID': '961'}), \
                patch.object(storage_worker, 'sh'), patch('os.chown') as chown:
            storage_worker.image_file(Path(directory) / 'p', 2**30)
        self.assertEqual({call.args[1:] for call in chown.call_args_list}, {(960, 961)})


if __name__ == '__main__':
    unittest.main()
