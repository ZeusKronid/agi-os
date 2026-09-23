"""Version of this Live image and the explicit "is there a newer AGIOS?" check.

The build writes version.json next to the website (scripts/build-iso.sh). Nothing here
talks to the network on its own: check() runs only when the user presses the button,
and it asks one fixed HTTPS endpoint (GitHub Releases of the AGIOS repository) for the
latest published release. Signature and checksum verification of a downloaded ISO is
described on the download page; this module only reports what is available.
"""
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

from settings import SOURCE_ROOT

VERSION_FILE = SOURCE_ROOT / 'version.json'
RELEASES = 'https://api.github.com/repos/ZeusKronid/agi-os/releases/latest'
DOWNLOAD_PAGE = 'https://github.com/ZeusKronid/agi-os/blob/main/docs/download.md'
TAG = re.compile(r'^v(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.]+))?$')
NOTES_LIMIT = 20_000
ANSWER_LIMIT = 2_000_000


def current(path=None):
    """What this image is: a release (tag v*) or a development build."""
    path = path or VERSION_FILE
    info = {'version': 'dev', 'release': False, 'revision': None, 'built': None, 'arch_snapshot': None}
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        data = {}
    if isinstance(data, dict):
        for key in ('version', 'revision', 'built', 'arch_snapshot', 'iso'):
            if isinstance(data.get(key), str):
                info[key] = data[key]
    info['release'] = parse(info['version']) is not None
    return info


def parse(version):
    """v1.2.3[-rc.1] → comparable key; anything else (dev builds) → None."""
    match = TAG.match(version or '')
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    numbers = (int(major), int(minor or 0), int(patch or 0))
    # A pre-release sorts before its release: v1.0.0-rc.1 < v1.0.0.
    return numbers + ((0, pre) if pre else (1, ''))


def newer(candidate, installed):
    a, b = parse(candidate), parse(installed)
    return a is not None and (b is None or a > b)


def fetch(url=RELEASES, timeout=15):
    if not url.startswith('https://api.github.com/'):
        raise ValueError('Адрес проверки обновлений должен вести на api.github.com')
    request = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'AGIOS-Live-update-check'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(ANSWER_LIMIT + 1)[:ANSWER_LIMIT])


def summary(release):
    """Only the fields the page shows, validated; links must stay on github.com."""
    if not isinstance(release, dict) or not isinstance(release.get('tag_name'), str):
        raise ValueError('Сервер обновлений вернул неожиданный ответ')

    def link(value):
        return value if isinstance(value, str) and value.startswith('https://github.com/') else None

    assets = []
    for asset in release.get('assets') or []:
        if isinstance(asset, dict) and isinstance(asset.get('name'), str):
            assets.append({'name': asset['name'], 'size': asset.get('size') if isinstance(asset.get('size'), int) else None,
                           'url': link(asset.get('browser_download_url'))})
    notes = release.get('body') if isinstance(release.get('body'), str) else ''
    return {'version': release['tag_name'], 'name': release.get('name') if isinstance(release.get('name'), str) else release['tag_name'],
            'published': release.get('published_at') if isinstance(release.get('published_at'), str) else None,
            'url': link(release.get('html_url')), 'notes': notes[:NOTES_LIMIT], 'assets': assets,
            'signed': any(a['name'] == 'SHA256SUMS.sig' for a in assets)}


def check(fetcher=None, installed=None):
    """One explicit check. Errors are reported to the page, never raised past it."""
    installed = installed or current()
    try:
        latest = summary((fetcher or fetch)())
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {'installed': installed, 'error': 'Опубликованных выпусков AGIOS пока нет'}
        return {'installed': installed, 'error': f'Не удалось проверить обновления: сервер ответил {error.code}'}
    except Exception as error:  # network, TLS, JSON, unexpected answer: the page shows it
        return {'installed': installed, 'error': f'Не удалось проверить обновления: {error}'}
    if not installed['release']:
        verdict = 'development'
    elif newer(latest['version'], installed['version']):
        verdict = 'update'
    else:
        verdict = 'latest'
    return {'installed': installed, 'latest': latest, 'verdict': verdict, 'download_page': DOWNLOAD_PAGE}
