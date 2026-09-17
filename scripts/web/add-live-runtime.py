#!/usr/bin/env python3
"""Prepare a local prototype from an existing Live root and host package cache."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import urllib.parse

repo = Path(__file__).resolve().parents[2]
root = repo/'.local/live-iso/root'
cache = Path('/var/cache/pacman/pkg')
(root/'var/lib/pacman/sync').mkdir(exist_ok=True)
for name in ('core.db','extra.db'):
    shutil.copyfile(Path('/var/lib/pacman/sync')/name, root/'var/lib/pacman/sync'/name)
lines = subprocess.check_output(['pacman','--dbpath',str(root/'var/lib/pacman'),'--config',str(repo/'archiso/pacman.conf'),'-Sp','--needed','--print-format','%n %v %l','qemu-system-x86','qemu-img','edk2-ovmf','qemu-ui-egl-headless','qemu-ui-opengl','qemu-hw-display-virtio-vga-gl','qemu-hw-display-virtio-vga','qemu-hw-display-virtio-gpu-gl','qemu-hw-display-virtio-gpu','qemu-hw-display-virtio-gpu-pci','qemu-hw-display-virtio-gpu-pci-gl','virglrenderer'],text=True).splitlines()
manifest = []
for line in lines:
    name,version,url = line.split(maxsplit=2)
    exact = url.rsplit('/',1)[-1]
    choices = [repo/'.local/live-payload/packages'/exact, cache/exact]
    choices += sorted(cache.glob(name+'-[0-9]*-x86_64.pkg.tar.zst'),reverse=True)
    choices += sorted(cache.glob(name+'-[0-9]*-any.pkg.tar.zst'),reverse=True)
    choices += sorted(cache.glob(name+'-[0-9]*-x86_64_v3.pkg.tar.zst'),reverse=True)
    package = None
    for candidate in choices:
        if not candidate.exists(): continue
        probe = subprocess.run(['bsdtar','-xOf',str(candidate),'.PKGINFO'],capture_output=True,text=True)
        if probe.returncode == 0 and ('pkgname = '+name+'\n') in probe.stdout:
            package = candidate
            metadata = probe.stdout
            break
    if package is None: raise SystemExit('Missing cached package: '+name)
    subprocess.run(['bsdtar','-xf',str(package),'-C',str(root),'--no-same-owner',
                    '--exclude=.PKGINFO','--exclude=.BUILDINFO','--exclude=.MTREE','--exclude=.INSTALL'],check=True)
    manifest.append({'package':name,'archive':package.name})
(repo/'.local/live-payload/runtime-packages.json').write_text(json.dumps(manifest,indent=2))
# aiohttp's Python implementations work across the Live Python version. Its
# optional CPython 3.13 native modules must not be copied into Python 3.14.
vendor = repo/'web/vendor'
vendor.mkdir(exist_ok=True)
site = next((repo/'.local/venv/lib').glob('python*/site-packages'))
for name in ('aiohttp','aiohappyeyeballs','aiosignal','attrs','attr','frozenlist','multidict','yarl','idna','propcache'):
    shutil.copytree(site/name,vendor/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('*.so','__pycache__'))
print('Runtime packages layered:',len(manifest))

for name in ('aiohttp','aiohappyeyeballs','aiosignal','attrs','frozenlist','multidict','yarl','idna','propcache'):
    for directory in site.glob(name+'-*.dist-info'):
        shutil.copytree(directory,vendor/directory.name,dirs_exist_ok=True)

# Optional modules for the development runner, without installing host packages.
# Only reuse modules built for this host QEMU version; mismatched modules can crash.
host_version = subprocess.check_output(['qemu-system-x86_64','--version'], text=True).splitlines()[0].split()[-1]
qemu_archive = next(item['archive'] for item in manifest if item['package'] == 'qemu-system-x86')
if qemu_archive.startswith('qemu-system-x86-' + host_version + '-'):
    host_runtime = repo/'.local/test-qemu'
    if host_runtime.exists(): shutil.rmtree(host_runtime)
    shutil.copytree(root/'usr/lib/qemu', host_runtime/'usr/lib/qemu')
    for library in (root/'usr/lib').glob('libvirglrenderer.so*'):
        shutil.copy2(library, host_runtime/'usr/lib'/library.name, follow_symlinks=False)
    license_dir = root/'usr/share/licenses/virglrenderer'
    if license_dir.exists():
        shutil.copytree(license_dir, host_runtime/'usr/share/licenses/virglrenderer')
else:
    stale_runtime = repo/'.local/test-qemu'
    if stale_runtime.exists(): shutil.rmtree(stale_runtime)
    print('Host QEMU differs from Live QEMU; install matching virtio GPU modules for the test runner.')
