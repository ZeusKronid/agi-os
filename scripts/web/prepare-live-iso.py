#!/usr/bin/env python3
"""Layer the local website and its inner installer onto a bootable Live ISO."""
import argparse
import hashlib
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base', type=Path, required=True)
parser.add_argument('--installer', type=Path, default=ROOT/'out/agi-os-web.iso')
args = parser.parse_args()
work = ROOT / '.local/live-iso'
work.mkdir(parents=True, exist_ok=True)
base, inner = args.base.resolve(), args.installer.resolve()
root, squash = work/'root', work/'base.sfs'
source_key = str(base) + ':' + str(base.stat().st_mtime_ns)

def run(*args):
    subprocess.run(args, check=True)

if not (work/'source').exists() or (work/'source').read_text() != source_key:
    if root.exists():
        shutil.rmtree(root)
    squash.unlink(missing_ok=True)
    run('xorriso','-osirrox','on','-indev',str(base),'-extract','/arch/x86_64/airootfs.sfs',str(squash))
    run('unsquashfs','-no-xattrs','-no-progress','-d',str(root),str(squash))
    (work/'source').write_text(source_key)
run('python',str(ROOT/'scripts/web/add-live-runtime.py'))
# Overlay source configuration, retaining the base's installed packages/kernel.
for source in (ROOT/'archiso/airootfs').rglob('*'):
    destination = root/source.relative_to(ROOT/'archiso/airootfs')
    if destination.is_symlink(): destination.unlink()
    elif destination.is_file(): destination.chmod(destination.stat().st_mode | stat.S_IWUSR)
shutil.copytree(ROOT/'archiso/airootfs', root, dirs_exist_ok=True, symlinks=True)
share = root/'usr/local/share/agi-os'
shutil.copytree(ROOT/'web', share/'web', dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('__pycache__','tests'))
shutil.copyfile(ROOT/'.local/guacamole.js', share/'web/static/guacamole.js')
licenses = root/'usr/share/licenses/agi-guacamole'
licenses.mkdir(parents=True, exist_ok=True)
for name in ('LICENSE','NOTICE'):
    shutil.copyfile(ROOT/'.local/guacamole-client-1.6.0'/name, licenses/name)
images = share/'images'
images.mkdir(exist_ok=True)
(images/'installer.iso').unlink(missing_ok=True)
(images/'installer.iso').symlink_to('/run/archiso/bootmnt/agi-os/installer.iso')
# guacd's pinned Alpine runtime needs no Docker daemon in the Live environment.
guacd = root/'opt/agi-guacd'
if not guacd.exists():
    guacd.mkdir(parents=True)
    with tarfile.open(ROOT/'.local/live-payload/guacd-rootfs.tar') as archive:
        members = [m for m in archive.getmembers() if not m.name.startswith('dev/') and not m.isdev()]
        archive.extractall(guacd, members=members, filter='fully_trusted')
(guacd/'tmp').mkdir(exist_ok=True)
(guacd/'tmp').chmod(0o1777)
# QA is inactive unless the external test runner supplies the dedicated port.
shutil.copyfile(ROOT/'scripts/web/qa-guest.py', share/'qa-guest.py')
unit = root/'etc/systemd/system/agi-qa.service'
unit.write_text('''[Unit]
Description=AGIOS test-only serial instrumentation
After=agi-web.service systemd-udev-settle.service
ConditionPathExists=/sys/firmware/qemu_fw_cfg/by_name/opt/org.agi-os.test/raw
ConditionPathExists=/dev/virtio-ports/org.agi-os.qa
[Service]
User=agi
Group=agi
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/agi/.Xauthority
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
ExecStart=/usr/bin/python -u /usr/local/share/agi-os/qa-guest.py
Restart=on-failure
[Install]
WantedBy=multi-user.target
''')
link = root/'etc/systemd/system/multi-user.target.wants/agi-qa.service'
link.unlink(missing_ok=True)
link.symlink_to('../agi-qa.service')
(root/'etc/udev/rules.d/73-agi-qa.rules').write_text('SUBSYSTEM=="virtio-ports", ATTR{name}=="org.agi-os.qa", GROUP="agi", MODE="0660"\n')
# A genuine Live desktop opens localhost; it is not the headless inner installer.
default = root/'etc/systemd/system/default.target'
default.unlink(missing_ok=True)
default.symlink_to('/usr/lib/systemd/system/graphical.target')
# Preserve original numeric owners/modes while assembling without host root.
listing = subprocess.check_output(['unsquashfs','-lln',str(squash)], text=True)
pseudo = []
for line in listing.splitlines():
    fields = line.split(maxsplit=5)
    if len(fields)!=6 or '/' not in fields[1] or not fields[5].startswith('squashfs-root/'):
        continue
    uid,gid = fields[1].split('/')
    name = fields[5].split(' -> ')[0].removeprefix('squashfs-root/')
    path = root/name
    if not path.exists() or path.is_symlink(): continue
    mode = sum(1 << (8-i) for i,c in enumerate(fields[0][1:10]) if c not in '-ST')
    if fields[0][3] in 'sS': mode |= stat.S_ISUID
    if fields[0][6] in 'sS': mode |= stat.S_ISGID
    if fields[0][9] in 'tT': mode |= stat.S_ISVTX
    if path.is_file() and not mode & stat.S_IRUSR: path.chmod(mode | stat.S_IRUSR)
    escaped = name.replace('\\','\\\\').replace('"','\\"')
    pseudo.append(f'"{escaped}" m {mode:o} {uid} {gid}')
metadata = work/'owners.pseudo'
metadata.write_text('\n'.join(pseudo)+'\n')
new = work/'live.sfs'
new.unlink(missing_ok=True)
run('mksquashfs',str(root),str(new),'-noappend','-no-xattrs','-all-root','-pseudo-override','-pf',str(metadata),'-comp','zstd','-processors','4','-no-progress')
with new.open('rb') as stream: checksum = hashlib.file_digest(stream,'sha512').hexdigest()
(work/'airootfs.sha512').write_text(checksum+'  airootfs.sfs\n')
target = ROOT/'out/agi-os-live-web.iso'
temp = target.with_suffix('.tmp.iso')
temp.unlink(missing_ok=True)
run('xorriso','-indev',str(base),'-outdev',str(temp),'-boot_image','any','replay',
    '-map',str(new),'/arch/x86_64/airootfs.sfs',
    '-map',str(work/'airootfs.sha512'),'/arch/x86_64/airootfs.sha512',
    '-map',str(inner),'/agi-os/installer.iso')
temp.replace(target)
print('Live ISO ready:',target)
