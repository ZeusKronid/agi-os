#!/usr/bin/env bash
# External test VM = the "computer". It boots the AGIOS Live ISO from an optical
# drive; the website, agent, Guacamole and the inner preview VM run inside it.
# Attached test disks: a blank target disk (serial AGIOS_TARGET) that plays the
# computer's own disk, and an optional second medium (an exFAT "USB stick").
# AGIOS_TEST_HARDWARE=laptop makes the "computer" a notebook: a Notebook SMBIOS
# chassis and an Intel HD Audio controller drive the driver plan and the "preview
# cannot verify" list; the NIC becomes an Intel e1000e so the inventory names it.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
mode=live firmware=uefi memory=10240 fresh=false target_size=20G iso=
while (($#)); do
    case "$1" in
        --mode) mode=$2; shift 2;;
        --firmware) firmware=$2; shift 2;;
        --memory) memory=$2; shift 2;;
        --target-size) target_size=$2; shift 2;;
        --iso) iso=$2; shift 2;;
        --fresh) fresh=true; shift;;
        *) echo 'Usage: run-live-web-vm.sh [--mode live|disk] [--firmware uefi|uefi-sb|bios] [--memory MiB] [--target-size 20G] [--iso PATH] [--fresh]' >&2; exit 1;;
    esac
done
[[ $mode == live || $mode == disk ]] || { echo 'Invalid mode' >&2; exit 1; }
[[ $firmware == uefi || $firmware == uefi-sb || $firmware == bios ]] || { echo 'Invalid firmware' >&2; exit 1; }
# uefi-sb: Secure Boot capable OVMF (SMM) whose fresh variable store has no keys, i.e.
# Setup Mode, as on a computer whose keys were cleared. Enrolled keys persist in
# .local/live-test/OVMF_VARS-uefi-sb.fd, so --mode disk then boots with Secure Boot on.
machine=q35
[[ $firmware == uefi-sb ]] && machine=q35,smm=on
if [[ -z $iso && $mode == live ]]; then
    shopt -s nullglob; images=(out/agi-os-20*-x86_64.iso); ((${#images[@]})) || { echo 'Build an ISO first: scripts/build-iso.sh' >&2; exit 1; }
    iso=${images[${#images[@]}-1]}
fi
[[ $mode == disk || -f "$iso" ]] || { echo "ISO not found: $iso" >&2; exit 1; }
[[ -r /dev/kvm && -w /dev/kvm ]] || { echo 'KVM unavailable'; exit 1; }
if [[ -r /sys/module/kvm_intel/parameters/nested ]]; then nested=$(cat /sys/module/kvm_intel/parameters/nested)
elif [[ -r /sys/module/kvm_amd/parameters/nested ]]; then nested=$(cat /sys/module/kvm_amd/parameters/nested)
else nested=N; fi
[[ $mode == disk || $nested == Y || $nested == 1 ]] || { echo 'Enable nested virtualization on the test host.'; exit 1; }
mkdir -p .local/live-test
target=.local/live-test-target.qcow2
if $fresh; then rm -f "$target" .local/live-test/OVMF_VARS-$firmware.fd; fi
if [[ ! -f $target ]]; then
    [[ $mode == live ]] || { echo 'No installed target disk'; exit 1; }
    qemu-img create -q -f qcow2 "$target" "$target_size"
fi
media=.local/live-test-media.img   # Optional: created by scripts/web/make-test-media.sh
bridge_dir= bridge_pid= qemu_pid=
cleanup() {
    if [[ -n "$qemu_pid" ]]; then kill "$qemu_pid" 2>/dev/null || true; wait "$qemu_pid" 2>/dev/null || true; fi
    if [[ -n "$bridge_pid" ]]; then
        kill "$bridge_pid" 2>/dev/null || true; wait "$bridge_pid" 2>/dev/null || true
        rm -f "$bridge_dir/llm.sock"; rmdir "$bridge_dir"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
cpus=6
if [[ $mode == disk ]]; then memory=4096 cpus=4; fi
# AGIOS_TEST_BRIDGE=none: no test bridge at all, so the Live behaves as on a real computer
# (for example to check the ChatGPT sign-in link, which the bridge otherwise stands in for).
if [[ $mode == live && ${AGIOS_TEST_BRIDGE:-} != none ]]; then
    bridge_dir=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/agios-live.XXXXXXXX")
    bridge_args=(--socket "$bridge_dir/llm.sock")
    # AGIOS_TEST_SCRIPTED=<config.json>: a fixed configuration instead of a live model (test only).
    [[ -n ${AGIOS_TEST_SCRIPTED:-} ]] && bridge_args+=(--scripted "$AGIOS_TEST_SCRIPTED")
    # AGIOS_TEST_BRIDGE=claude-code: route the dialogue through the host's headless Claude Code.
    [[ -n ${AGIOS_TEST_BRIDGE:-} ]] && bridge_args+=(--backend "$AGIOS_TEST_BRIDGE")
    python -B scripts/dev-bridge.py "${bridge_args[@]}" > .local/live-test/bridge.log 2>&1 &
    bridge_pid=$!
    for attempt in {1..100}; do [[ -S "$bridge_dir/llm.sock" ]] && break; sleep .1; done
    [[ -S "$bridge_dir/llm.sock" ]] || { echo 'LLM test bridge failed'; exit 1; }
fi
# No KVM async page faults for the outer guest: with nested virtualization and host
# memory pressure they left guest tasks stuck in kvm_async_pf_task_wait forever.
args=(-name "AGIOS Live boot — test computer ($firmware)" -machine "$machine" -accel kvm -cpu host,kvm-asyncpf=off,kvm-asyncpf-int=off
      -m "$memory" -smp "$cpus" -display none -vga std -vnc 127.0.0.1:97
      -device qemu-xhci -device usb-tablet
      -device virtio-balloon-pci,free-page-reporting=on
      -drive "file=$repo/$target,format=qcow2,if=none,id=target,discard=unmap,detect-zeroes=unmap"
      -device virtio-blk-pci,drive=target,serial=AGIOS_TARGET,bootindex=3
      -qmp "unix:$repo/.local/live-test/qmp.sock,server=on,wait=off")
if [[ $mode == disk ]]; then
    # Q35's emulated ICH9 TCO watchdog may fire after a hibernation image is
    # restored. Its default reset action destroys the resumed session; keep the
    # watchdog event visible through QMP without resetting this test computer.
    args+=(-action watchdog=none)
fi
if [[ $firmware == uefi || $firmware == uefi-sb ]]; then
    vars=.local/live-test/OVMF_VARS-$firmware.fd code=/usr/share/edk2/x64/OVMF_CODE.4m.fd
    [[ -f $vars ]] || cp /usr/share/edk2/x64/OVMF_VARS.4m.fd "$vars"
    if [[ $firmware == uefi-sb ]]; then
        code=/usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd
        args+=(-global driver=cfi.pflash01,property=secure,value=on)
    fi
    args+=(-drive "if=pflash,format=raw,readonly=on,file=$code"
           -drive "if=pflash,format=raw,file=$repo/$vars")
fi
if [[ $mode == live ]]; then
    args+=(-nic "user,model=$([[ ${AGIOS_TEST_HARDWARE:-} == laptop ]] && echo e1000e || echo virtio-net-pci)"
           -fw_cfg name=opt/org.agi-os.test,string=1
           -device virtio-serial-pci)
    [[ -n $bridge_dir ]] && args+=(-chardev "socket,id=llm,path=$bridge_dir/llm.sock"
                                   -device virtserialport,chardev=llm,name=org.agi-os.llm)
    args+=(-chardev "socket,id=qa,path=$repo/.local/live-test/qa.sock,server=on,wait=off"
           -device virtserialport,chardev=qa,name=org.agi-os.qa
           -drive "file=$iso,media=cdrom,readonly=on,if=none,id=live"
           -device ide-cd,drive=live,bootindex=1)
    if [[ -f $media ]]; then
        args+=(-drive "file=$repo/$media,format=raw,if=none,id=media"
               -device usb-storage,drive=media,serial=AGIOS_MEDIA,removable=on)
    fi
    if [[ -n ${AGIOS_TEST_MIRROR:-} ]]; then
        args+=(-fw_cfg "name=opt/org.agi-os.test-mirror,string=$AGIOS_TEST_MIRROR")
    fi
    if [[ -n ${AGIOS_TEST_CACHE_ISO:-} ]]; then
        [[ -f "$AGIOS_TEST_CACHE_ISO" ]] || { echo 'QA package cache ISO missing'; exit 1; }
        args+=(-drive "file=$AGIOS_TEST_CACHE_ISO,media=cdrom,readonly=on,if=none,id=testcache"
               -device ide-cd,drive=testcache,bus=ide.1)
    fi
else
    # The installed system's serial console (add console=ttyS0 to its kernel command line to see it).
    args+=(-nic "user,model=$([[ ${AGIOS_TEST_HARDWARE:-} == laptop ]] && echo e1000e || echo virtio-net-pci)"
           -serial "file:$repo/.local/live-test/serial.log")
fi
if [[ ${AGIOS_TEST_HARDWARE:-} == laptop ]]; then
    chassis=.local/live-test/smbios-chassis-notebook.bin
    python - "$chassis" <<'PY'
import struct, sys
# SMBIOS type 3 (chassis) v2.7 record: type 10 = Notebook, so the Live sees a laptop.
strings = [b"AGIOS QA", b"1.0", b"QA-CHASSIS-1", b"QA-ASSET", b"QA-SKU"]
body = struct.pack("<BBHBBBBBBBBBIBBBBB", 3, 0x16, 0x0300, 1, 10, 2, 3, 4, 3, 3, 3, 3, 0, 0, 0, 0, 0, 5)
open(sys.argv[1], "wb").write(body + b"\0".join(strings) + b"\0\0")
PY
    args+=(-smbios type=1,manufacturer="AGIOS QA",product="Test Laptop" -smbios "file=$chassis"
           -audiodev none,id=snd0 -device ich9-intel-hda -device hda-duplex,audiodev=snd0)
fi
# Hard memory cap for the whole test machine so a busy guest can never push the host into swap.
runner=()
if command -v systemd-run >/dev/null; then
    runner=(systemd-run --user --scope --quiet -p "MemoryMax=$((memory + 1536))M" -p "MemorySwapMax=0")
fi
"${runner[@]}" qemu-system-x86_64 "${args[@]}" > .local/live-test/qemu.log 2>&1 &
qemu_pid=$!
wait "$qemu_pid"
