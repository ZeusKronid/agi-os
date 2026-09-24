"""Version of the Live image and the explicit update check (CMP-137)."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release
import server
from aiohttp.test_utils import AioHTTPTestCase
from controller import DemoProvider
from system import demo_inventory


def github_release(tag='v0.2.0', **extra):
    return {'tag_name': tag, 'name': f'AGIOS {tag}', 'published_at': '2026-10-01T10:00:00Z',
            'html_url': f'https://github.com/ZeusKronid/agi-os/releases/tag/{tag}', 'body': '## Changes\n- Faster preview',
            'assets': [{'name': f'agi-os-2026.10.01-x86_64.iso', 'size': 2_000_000_000,
                        'browser_download_url': f'https://github.com/ZeusKronid/agi-os/releases/download/{tag}/agi-os.iso'},
                       {'name': 'SHA256SUMS.sig', 'size': 566,
                        'browser_download_url': 'https://evil.example/SHA256SUMS.sig'}], **extra}


class VersionTests(unittest.TestCase):
    def write(self, data):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'version.json'
        path.write_text(data if isinstance(data, str) else json.dumps(data))
        return path

    def test_missing_or_broken_file_is_a_development_build(self):
        self.assertEqual(release.current(Path('/nonexistent/version.json'))['version'], 'dev')
        info = release.current(self.write('{broken'))
        self.assertEqual((info['version'], info['release']), ('dev', False))

    def test_release_build(self):
        info = release.current(self.write({'version': 'v0.1.0', 'revision': 'abc', 'built': '2026-09-23T10:00:00Z',
                                           'arch_snapshot': '2026/09/20', 'extra': 'ignored'}))
        self.assertTrue(info['release'])
        self.assertEqual(info['revision'], 'abc')
        self.assertNotIn('extra', info)

    def test_versions_compare_numerically_and_prereleases_first(self):
        ordered = ['v0.9.0', 'v0.10.0-rc.1', 'v0.10.0', 'v0.10.1', 'v1', 'v1.0.1']
        keys = [release.parse(v) for v in ordered]
        self.assertEqual(keys, sorted(keys))
        self.assertIsNone(release.parse('dev'))
        self.assertIsNone(release.parse('2026.09.23'))
        self.assertTrue(release.newer('v0.2.0', 'v0.1.9'))
        self.assertFalse(release.newer('v0.1.0', 'v0.1.0'))
        self.assertFalse(release.newer('nightly', 'v0.1.0'))

    def test_only_github_api_is_contacted(self):
        with self.assertRaises(ValueError):
            release.fetch('http://api.github.com/repos/x/y/releases/latest')
        with self.assertRaises(ValueError):
            release.fetch('https://example.com/releases/latest')


class CheckTests(unittest.TestCase):
    installed = {'version': 'v0.1.0', 'release': True, 'revision': 'abc', 'built': None, 'arch_snapshot': None}

    def test_newer_release_is_offered_with_notes_and_safe_links(self):
        result = release.check(lambda: github_release('v0.2.0'), self.installed)
        self.assertEqual(result['verdict'], 'update')
        latest = result['latest']
        self.assertEqual(latest['version'], 'v0.2.0')
        self.assertIn('Faster preview', latest['notes'])
        self.assertTrue(latest['signed'])
        # Links that leave github.com are dropped rather than shown.
        self.assertEqual([a['url'] for a in latest['assets']][1], None)
        self.assertTrue(latest['url'].startswith('https://github.com/'))

    def test_same_release_is_latest(self):
        self.assertEqual(release.check(lambda: github_release('v0.1.0'), self.installed)['verdict'], 'latest')

    def test_development_build_only_reports_the_latest_release(self):
        dev = {**self.installed, 'version': 'dev', 'release': False}
        self.assertEqual(release.check(lambda: github_release('v0.2.0'), dev)['verdict'], 'development')

    def test_errors_become_a_message(self):
        def offline():
            raise OSError('Network is unreachable')
        result = release.check(offline, self.installed)
        self.assertIn('Network is unreachable', result['error'])
        result = release.check(lambda: {'message': 'Not Found'}, self.installed)
        self.assertIn('unexpected response', result['error'])

    def test_no_releases_yet(self):
        import urllib.error
        def missing():
            raise urllib.error.HTTPError(release.RELEASES, 404, 'Not Found', {}, None)
        self.assertEqual(release.check(missing, self.installed)['error'], 'No AGIOS releases are published yet')

    def test_notes_are_bounded(self):
        result = release.check(lambda: github_release('v0.2.0', body='x' * 100_000), self.installed)
        self.assertEqual(len(result['latest']['notes']), release.NOTES_LIMIT)


class VersionApiTests(AioHTTPTestCase):
    async def get_application(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        (Path(self.directory.name) / 'web/static').mkdir(parents=True)
        for target, value in (('ROOT', Path(self.directory.name)), ('LiveProvider', DemoProvider),
                              ('DATA_ROOT', Path(self.directory.name)),
                              ('target_inventory', lambda: {**demo_inventory(), 'live': True})):
            patcher = patch.object(server, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return server.application()

    async def test_version_is_readable(self):
        with patch.object(release, 'VERSION_FILE', Path(self.directory.name) / 'version.json'):
            response = await self.client.get('/api/version', headers={'Host': 'localhost:8787'})
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['version'], 'dev')

    async def test_check_needs_a_local_page_request(self):
        with patch.object(release, 'fetch', side_effect=AssertionError('must not be called')):
            response = await self.client.post('/api/version/check', json={}, headers={'Host': 'localhost:8787'})
            self.assertEqual(response.status, 403)

    async def test_check_runs_on_request(self):
        with patch.object(release, 'fetch', return_value=github_release('v9.0.0')) as fetch:
            response = await self.client.post('/api/version/check', json={},
                                              headers={'Host': 'localhost:8787', 'X-AGIOS': 'local'})
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())['latest']['version'], 'v9.0.0')
            fetch.assert_called_once()


if __name__ == '__main__':
    unittest.main()
