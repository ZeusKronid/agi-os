"""Repackage the existing live ISO with a virtio installation service.

This headless build runs its installer as root inside the VM. The original ISO
is preserved. File capabilities aren't needed by this service and are omitted.
"""
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
base = Path(sys.argv[1]).resolve()
work = ROOT / '.local/web-iso'
work.mkdir(parents=True, exist_ok=True)
target = ROOT / 'out/agi-os-web.iso'
inputs = [ROOT / 'web/guest.py', Path(__file__), *sorted((ROOT / 'archiso/airootfs/usr/local/share/agi-os/installer').glob('*.py'))]
fingerprint = hashlib.sha256((str(base) + str(base.stat().st_mtime_ns)).encode() + b''.join(p.read_bytes() for p in inputs)).hexdigest()
stamp = work / 'stamp'
if target.exists() and stamp.exists() and stamp.read_text() == fingerprint:
    print('Web ISO is current')
    sys.exit()

def run(*args):
    subprocess.run(args, check=True)

squash = work / 'base.sfs'
source_stamp = work / 'source'
source_key = str(base) + ':' + str(base.stat().st_mtime_ns)
root = work / 'root'
if not source_stamp.exists() or source_stamp.read_text() != source_key:
    # Work files are generated exclusively by this script.
    if root.exists():
        shutil.rmtree(root)
    squash.unlink(missing_ok=True)
    run('xorriso', '-osirrox', 'on', '-indev', str(base), '-extract', '/arch/x86_64/airootfs.sfs', str(squash))
    run('unsquashfs', '-no-xattrs', '-no-progress', '-d', str(root), str(squash))
    source_stamp.write_text(source_key)
engine = root / 'usr/local/share/agi-os/installer'
for path in (ROOT / 'archiso/airootfs/usr/local/share/agi-os/installer').glob('*.py'):
    shutil.copyfile(path, engine / path.name)
shutil.copyfile(ROOT / 'web/guest.py', engine / 'web-guest.py')
# Prefer the geographically routed mirror over a potentially unreachable CDN.
mirrorlist = root / 'etc/pacman.d/mirrorlist'
mirrors = mirrorlist.read_text()
geo = 'Server = https://geo.mirror.pkgbuild.com/$repo/os/$arch'
mirrors = '\n'.join(line for line in mirrors.splitlines() if line != geo)
mirrorlist.write_text(geo + '\n' + mirrors + '\n')
unit = root / 'etc/systemd/system/agi-web-install.service'
unit.write_text('''[Unit]
Description=AGIOS local web installation channel
After=multi-user.target
ConditionPathExists=/dev/virtio-ports/org.agi-os.install
[Service]
Type=simple
ExecStart=/usr/bin/python -u /usr/local/share/agi-os/installer/web-guest.py
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
'''.replace('After=multi-user.target', 'After=systemd-udev-settle.service\nWants=systemd-udev-settle.service'))
link = root / 'etc/systemd/system/multi-user.target.wants/agi-web-install.service'
link.unlink(missing_ok=True)
link.symlink_to('../agi-web-install.service')
default = root / 'etc/systemd/system/default.target'
default.unlink(missing_ok=True)
default.symlink_to('/usr/lib/systemd/system/multi-user.target')
# Preserve non-root owner/group IDs from the original filesystem through pseudo
# metadata; extraction itself is unprivileged. Files default to root ownership.
listing = subprocess.check_output(['unsquashfs', '-lln', str(squash)], text=True)
pseudo = []
for line in listing.splitlines():
    fields = line.split(maxsplit=5)
    if len(fields) != 6 or '/' not in fields[1] or not fields[5].startswith('squashfs-root/'):
        continue
    uid, gid = fields[1].split('/')
    name = fields[5].split(' -> ')[0].removeprefix('squashfs-root/')
    path = root / name
    if path.exists() and not path.is_symlink():
        mode = 0
        for index, flag in enumerate(fields[0][1:10]):
            if flag not in '-ST':
                mode |= 1 << (8 - index)
        if fields[0][3] in 'sS': mode |= stat.S_ISUID
        if fields[0][6] in 'sS': mode |= stat.S_ISGID
        if fields[0][9] in 'tT': mode |= stat.S_ISVTX
        if path.is_file() and not mode & stat.S_IRUSR:
            path.chmod(mode | stat.S_IRUSR)
        escaped = name.replace('\\', '\\\\').replace('"', '\\"')
        pseudo.append(f'"{escaped}" m {mode:o} {uid} {gid}')
metadata = work / 'owners.pseudo'
metadata.write_text('\n'.join(pseudo) + '\n')
new_squash = work / 'web.sfs'
new_squash.unlink(missing_ok=True)
run('mksquashfs', str(root), str(new_squash), '-noappend', '-no-xattrs', '-all-root','-pseudo-override', '-pf', str(metadata), '-comp', 'zstd', '-processors', '4', '-no-progress')
checksum = work / 'airootfs.sha512'
with new_squash.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha512').hexdigest()
checksum.write_text(digest + '  airootfs.sfs\n')
temporary = target.with_suffix('.tmp.iso')
temporary.unlink(missing_ok=True)
run('xorriso', '-indev', str(base), '-outdev', str(temporary), '-boot_image', 'any', 'replay',
    '-map', str(new_squash), '/arch/x86_64/airootfs.sfs', '-map', str(checksum), '/arch/x86_64/airootfs.sha512')
temporary.replace(target)
stamp.write_text(fingerprint)
print('Prepared', target)
