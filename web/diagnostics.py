"""One-click diagnostics bundle of the Live session, safe to send to the developers.

The archive holds what is needed to understand a failure and nothing secret:
journald records of AGIOS components and services of this boot, the session
record, the site state and the hardware inventory, versions, and the tails of
the preview VM logs. Every file passes journal.redact(); passwords and the LUKS
passphrase never reach the site's records in the first place, disk serial
numbers are shortened.
"""
import io
import json
from pathlib import Path
import platform
import subprocess
import tarfile
import time

from journal import IDENTIFIERS, redact

UNITS = ('agi-web.service', 'agi-guacd.service', 'agi-guest.service', 'agi-qa.service', 'choose-mirror.service',
         'pacman-init.service', 'NetworkManager.service')
PACKAGES = ('linux', 'systemd', 'python', 'python-aiohttp', 'qemu-base', 'qemu-system-x86', 'edk2-ovmf',
            'pacman', 'arch-install-scripts', 'cryptsetup', 'firefox')
JOURNAL_FIELDS = ('SYSLOG_IDENTIFIER', '_SYSTEMD_UNIT', 'PRIORITY', 'MESSAGE', '_PID', '_UID',
                  'AGIOS_EVENT', 'AGIOS_OPERATION', 'AGIOS_DATA', 'AGIOS_ERROR')
LOG_TAIL = 256 * 1024
JOURNAL_LINES = 20_000
README = '''Диагностика AGIOS

Этот архив создан кнопкой «Диагностика» на сайте Live-среды AGIOS. Он нужен,
чтобы разработчики поняли, что произошло. Пароли пользователя и шифрования
сайт не сохраняет; ключи API, токены, хэши паролей и значения полей с
«секретными» именами заменены на *** автоматически, серийные номера дисков
сокращены. Фильтр узнаёт секреты только по виду: диалог с агентом (session.json)
включён целиком — если вы писали в чат пароль или ключ обычным текстом,
удалите его. Перед отправкой откройте файлы и проверьте содержимое.

Файлы:
  versions.json          — версия образа, ревизия исходников, ядро, пакеты
  state.json             — состояние сайта: этап, конфигурация, события, ошибки
  session.json           — запись сеанса: диалог с агентом, конфигурация, этапы
  inventory.json         — диски и железо компьютера
  journal-agios.jsonl    — журнал компонентов AGIOS за эту загрузку
  journal-services.jsonl — журнал служб Live (сайт, guacd, зеркала, сеть)
  journal-warnings.jsonl — предупреждения и ошибки всей системы за загрузку
  vm/<VM>/qemu.log, vm/<VM>/guest-console.log — хвосты журналов VM превью
'''


def command(args, timeout=30):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return '', f'{args[0]}: {type(exc).__name__}'
    return result.stdout, result.stderr.strip()


def read_text(path, tail=None):
    try:
        with open(path, 'rb') as stream:
            if tail:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(max(0, size - tail))
                data = stream.read()
                prefix = f'[… начало обрезано, показаны последние {tail} байт]\n' if size > tail else ''
                return prefix + data.decode('utf-8', 'replace')
            return stream.read().decode('utf-8', 'replace')
    except OSError:
        return None


def mask_serials(value):
    """Keep the last four characters of disk serials and WWNs: enough to tell disks apart."""
    if isinstance(value, dict):
        return {k: (('…' + v[-4:]) if k in ('serial', 'wwn') and isinstance(v, str) and len(v) > 4 else mask_serials(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [mask_serials(v) for v in value]
    return value


def journal_records(args):
    """Selected fields of journald JSON records; the reader's own access limits apply."""
    out, err = command(['journalctl', '--no-pager', '-b', '-o', 'json', '-n', str(JOURNAL_LINES), *args], timeout=60)
    lines = []
    for raw in out.splitlines():
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        entry = {'time': record.get('__REALTIME_TIMESTAMP')}
        for key in JOURNAL_FIELDS:
            value = record.get(key)
            if isinstance(value, list):
                # Non-UTF-8 values are exported as byte arrays.
                value = bytes(v for v in value if isinstance(v, int) and 0 <= v < 256).decode('utf-8', 'replace')
            if value is not None:
                entry[key] = value
        lines.append(json.dumps(redact(entry), ensure_ascii=False))
    if err and not lines:
        lines.append(json.dumps({'note': 'Журнал недоступен: ' + redact(err)[:500]}, ensure_ascii=False))
    return '\n'.join(lines) + '\n'


def versions(share):
    packages, _ = command(['pacman', '-Q', *PACKAGES])
    iso = next((text.strip() for text in (read_text(p) for p in ('/version', '/run/archiso/bootmnt/arch/version')) if text), None)
    os_release = read_text('/etc/os-release') or ''
    return {'iso_version': iso, 'source_revision': (read_text(Path(share) / 'source-revision') or '').strip() or None,
            'kernel': platform.release(), 'python': platform.python_version(),
            'os_release': dict(line.split('=', 1) for line in os_release.splitlines() if '=' in line),
            'packages': dict(line.split(' ', 1) for line in packages.splitlines() if ' ' in line),
            'created': time.strftime('%Y-%m-%dT%H:%M:%S%z')}


def vm_logs(data_root, limit=4):
    """Tails of the newest preview VM logs."""
    directories = sorted((p for p in (Path(data_root) / 'vm').glob('web-*') if p.is_dir()),
                         key=lambda p: p.name, reverse=True)[:limit]
    files = {}
    for directory in directories:
        for name in ('qemu.log', 'guest-console.log'):
            text = read_text(directory / name, tail=LOG_TAIL)
            if text is not None:
                files[f'vm/{directory.name}/{name}'] = redact(text)
    return files


def bundle(state, inventory, data_root, share):
    """The diagnostics archive as .tar.gz bytes. state is the site's public state."""
    files = {'README.txt': README,
             'versions.json': json.dumps(redact(versions(share)), ensure_ascii=False, indent=1),
             'state.json': json.dumps(mask_serials(redact(state)), ensure_ascii=False, indent=1),
             'inventory.json': json.dumps(mask_serials(redact(inventory)), ensure_ascii=False, indent=1)}
    session = read_text(Path(data_root) / 'session.json')
    if session is not None:
        try:
            files['session.json'] = json.dumps(mask_serials(redact(json.loads(session))), ensure_ascii=False, indent=1)
        except ValueError:
            files['session.json'] = redact(session)
    files['journal-agios.jsonl'] = journal_records([arg for name in IDENTIFIERS for arg in ('-t', name)])
    files['journal-services.jsonl'] = journal_records([arg for unit in UNITS for arg in ('-u', unit)])
    files['journal-warnings.jsonl'] = journal_records(['-p', 'warning'])
    files.update(vm_logs(data_root))
    buffer = io.BytesIO()
    stamp = time.time()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for name, text in files.items():
            data = text.encode('utf-8')
            info = tarfile.TarInfo('agios-diagnostics/' + name)
            info.size, info.mtime, info.mode = len(data), stamp, 0o600
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()
