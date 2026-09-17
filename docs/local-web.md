# AGIOS Live website and preview VM

AGIOS is a bootable Live ISO. **Inside the Live environment**, Firefox opens
`http://localhost:8787`. The conversation controller, provider adapter, Guacamole
and QEMU all run in that Live environment. After configuration review, the site
creates a new virtual disk and starts a preview VM. The existing installer runs
inside that VM, installs the agreed system and restarts it without its ISO.
Guacamole displays the resulting system on the same localhost page.

For development only, the Live ISO is itself booted in an external QEMU machine.
That outer VM substitutes for the physical computer. Thus the test uses nested
virtualization; a real boot from USB needs only ordinary hardware virtualization.
The host does not run the AGIOS website or its Guacamole gateway.

## Build and test locally

```sh
./scripts/prepare-web.sh
./scripts/run-live-web-vm.sh
```

`run-installer.sh` and `run-web.sh` are aliases for the external Live-ISO test
launcher. They do not launch the website on the host. `run-native-installer.sh`
retains the previous native interface for engine debugging only.

The local prototype build uses the existing desktop ISO and cached QEMU/runtime
packages, avoiding another privileged complete Archiso build. It records the
actual runtime package archives in `.local/live-payload/runtime-packages.json`.
On this CachyOS development machine the cache can include CPU-optimized library
builds; this particular prototype is tested on this computer's CPU, not claimed
as a portable release for older hardware. A clean release build should install
all runtime dependencies from the official repositories during Archiso assembly.

Requirements: the original desktop ISO, QEMU packages in the local cache,
`qemu-img`, KVM, `edk2-ovmf`, `uv`, Docker access for retrieving the pinned guacd
runtime, `xorriso`, `bsdtar` and squashfs tools. The browser client and guacd are
Apache Guacamole 1.6.0. Docker is used only while preparing the runtime bundle;
there is no Docker daemon inside the Live environment. Guacd runs as a systemd
service using its bundled userspace. Python's optional aiohttp native extensions
are omitted from the vendored runtime so it matches the Live Python interpreter.

Outputs:

- `out/agi-os-live-web.iso`: user-facing Live ISO with the localhost website.
- `out/agi-os-web.iso`: headless installation image, embedded on the Live ISO
  as `/agi-os/installer.iso`, used only to install the inner preview VM.

The test launcher allocates 10 GiB RAM to the outer machine and passes the host
CPU's virtualization features through. A separately created, clearly labelled
48 GiB test workspace image is mounted inside the outer Live environment.
The mount helper runs only with an explicit test firmware marker and accepts only
that labelled, serial-numbered virtual device. It never formats a device.
No physical host block devices are attached to either machine.

## Live runtime

- `agi-web.service`: website/controller at `127.0.0.1:8787`, running as `agi`.
- `agi-guacd.service`: local Guacamole gateway at `127.0.0.1:14822`.
- `agi-installer`: opens the website in the Live desktop's Firefox.
- `web/runtime.py`: starts the inner QEMU VM, owns its disk and installation link.
- `web/guest.py`: installation service in the inner VM's temporary boot image.

Virtual disks and dialogue state are under `/var/lib/agi-os`. During an ordinary
Live boot this is temporary Live storage: rebooting the Live environment loses
that session unless storage is explicitly persisted. During our test it lives on
the separate test workspace image. The final-install stage lists eligible disks and requires a separate review,
preview acceptance and typed disk path before writing. A VM disk is 32 GiB virtual capacity; actual space grows with use.

The default real Live session asks the user to connect a provider in the site's
settings. ChatGPT login opens a browser tab **inside the Live environment**;
API providers and Ollama use the existing adapters. Provider credentials and the
new system's password are not included in the conversation or session file.

The external test launcher may connect the pre-existing development LLM bridge
through a private virtio port, using the host's existing Codex login only as a
model-provider connection. The website, dialogue controller, configuration
validation, installation orchestration, Guacamole and inner VM still run inside
Live. Host credentials are not copied into either VM.

There is no screenshot feature in the product. Screenshots are captured externally
by test tooling and collected in the standalone HTML visual report.

The flow is Live → agent proposal → preview VM → clean guest shutdown → final
disk review → transfer → boot from the final disk. Transfer currently supports
UEFI and ext4. It copies the exact preview image, verifies its bytes, expands the
root filesystem to the destination disk, regenerates initramfs and installs the
bootloader. User files and passwords survive. The final machine receives a new
first-boot acceptance ID, so preview success cannot count as final-boot success.
Source changes or a replacement destination invalidate the confirmation.

In-place modification, snapshots and image export remain outside this version. Stopping a VM is immediate; shut down inside
the guest first when a clean shutdown is needed.

## Verification

```sh
python -B -m unittest discover -s tests -v
.local/venv/bin/python -B -m unittest discover -s web/tests -v
node --check web/static/app.js
```

Test instrumentation (`org.agi-os.qa`) is a separate serial channel, activated
only in the explicitly marked outer test VM. It is not a model tool or website
API. The host-side QA transport and forwarded WebDriver port control only the
test machine; they do not host the user-facing application.

For repeatable QA when the external network is slow, the test launcher optionally
accepts `AGIOS_TEST_CACHE_ISO=/absolute/path/to/package-cache.iso`. The optical
image must have label `AGIOS_CACHE`, with `core.db`, `extra.db` and their matching
signed package archives at its root. It is attached read-only through both VM
levels. Only the explicitly marked test environment forwards it to the inner
installer; that installer uses it as a temporary file mirror in its live
`pacman.conf`. Package signature verification stays enabled. The installed
system retains its normal `pacman.conf` and official network mirrorlist. The
cache is not bundled into the user-facing Live ISO and is not needed for normal
networked installation.

## Final-disk development test

The outer test VM owns a separate 40 GiB `.local/live-test-final.qcow2`, serial
`AGIOS_TARGET`. In a marked test VM, only this serial is eligible for deployment;
the mounted workspace is not a target. After successful deployment, shut down
Live and run `scripts/run-live-web-vm.sh --mode disk`. This boots the final disk
without the Live ISO, workspace or package cache.

The tested Hyprland path uses virtio-vga with Mesa software rendering. Accelerated
nested 3D did not pass the display test and is opt-in: `AGIOS_TEST_GL=1` for the
outer launcher, `AGIOS_PREVIEW_GL=1` in the Live service for the inner VM. These
experimental modes use EGL headless, virtio-vga-gl and a render node. The host
launcher accepts `AGIOS_RENDER_NODE`; otherwise it prefers a non-NVIDIA node.
QEMU needs matching virtio GPU, OpenGL, EGL and virglrenderer modules. Software
rendering is sufficient for this prototype test, not a performance claim.
