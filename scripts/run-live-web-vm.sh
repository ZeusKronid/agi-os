#!/usr/bin/env bash
# External VM is only the test computer. The website and preview VM run inside it.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo"
mode=live
if [[ ${1:-} == --mode ]]; then mode=${2:-}; shift 2; fi
[[ $# == 0 && ( $mode == live || $mode == disk ) ]] || { echo 'Usage: run-live-web-vm.sh [--mode live|disk]'; exit 1; }
iso=${AGIOS_LIVE_ISO:-$repo/out/agi-os-live-web.iso}
[[ $mode == disk || -f "$iso" ]] || { echo 'Build out/agi-os-live-web.iso first.' >&2; exit 1; }
[[ -r /dev/kvm && -w /dev/kvm ]] || { echo 'KVM unavailable'; exit 1; }
if [[ -r /sys/module/kvm_intel/parameters/nested ]]; then
    nested=$(cat /sys/module/kvm_intel/parameters/nested)
elif [[ -r /sys/module/kvm_amd/parameters/nested ]]; then
    nested=$(cat /sys/module/kvm_amd/parameters/nested)
else nested=N; fi
[[ $mode == disk || $nested == Y || $nested == 1 ]] || { echo 'Enable nested virtualization on the test host.'; exit 1; }
mkdir -p .local/live-test
if [[ $mode == live && ! -f .local/live-test-workspace.img ]]; then
    truncate -s 48G .local/live-test-workspace.img
    mkfs.ext4 -q -F -L AGIOS_TESTDATA -E root_owner="$(id -u):$(id -g)" .local/live-test-workspace.img
fi
if [[ ! -f .local/live-test-final.qcow2 ]]; then
    [[ $mode == live ]] || { echo 'No installed final test disk'; exit 1; }
    qemu-img create -q -f qcow2 .local/live-test-final.qcow2 40G
fi
[[ -f .local/live-test/OVMF_VARS.fd ]] || cp /usr/share/edk2/x64/OVMF_VARS.4m.fd .local/live-test/OVMF_VARS.fd
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
memory=4096 cpus=4
if [[ $mode == live ]]; then
    memory=10240 cpus=6
    bridge_dir=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/agios-live.XXXXXXXX")
    python -B scripts/dev-bridge.py --socket "$bridge_dir/llm.sock" > .local/live-test/bridge.log 2>&1 &
    bridge_pid=$!
    for attempt in {1..100}; do [[ -S "$bridge_dir/llm.sock" ]] && break; sleep .1; done
    [[ -S "$bridge_dir/llm.sock" ]] || { echo 'LLM test bridge failed'; exit 1; }
fi
# The rootless ISO build also prepares matching optional host QEMU modules.
if [[ -z ${QEMU_MODULE_DIR:-} && -d .local/test-qemu/usr/lib/qemu ]]; then
    export QEMU_MODULE_DIR="$repo/.local/test-qemu/usr/lib/qemu"
    export LD_LIBRARY_PATH="$repo/.local/test-qemu/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
# No website/guacd listener runs on the host. Only QA WebDriver and the external
# VM console are forwarded for test automation. Normal use boots the ISO on metal.
render=${AGIOS_RENDER_NODE:-}
if [[ -z $render ]]; then
    for candidate in /sys/class/drm/renderD*; do
        [[ $(readlink -f "$candidate/device/driver") == */nvidia ]] && continue
        render=/dev/dri/${candidate##*/}; break
    done
fi
graphics=(-display none -device virtio-vga)
if [[ ${AGIOS_TEST_GL:-0} == 1 && -n $render && -r $render && -w $render ]]; then
    graphics=(-display "egl-headless,rendernode=$render" -device virtio-vga-gl)
fi
args=(-name 'AGIOS Live boot — test computer' -machine q35 -accel kvm -cpu host
      -m "$memory" -smp "$cpus" "${graphics[@]}" -vnc 127.0.0.1:97
      -device qemu-xhci -device usb-tablet
      -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd
      -drive "if=pflash,format=raw,file=$repo/.local/live-test/OVMF_VARS.fd"
      -drive "file=$repo/.local/live-test-final.qcow2,format=qcow2,if=none,id=final,discard=unmap,detect-zeroes=unmap"
      -device virtio-blk-pci,drive=final,serial=AGIOS_TARGET,bootindex=3
      -qmp "unix:$repo/.local/live-test/qmp.sock,server=on,wait=off")
if [[ $mode == live ]]; then
    args+=(-nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:14444-:4444
           -fw_cfg name=opt/org.agi-os.test,string=1
           -device virtio-serial-pci
           -chardev "socket,id=llm,path=$bridge_dir/llm.sock"
           -device virtserialport,chardev=llm,name=org.agi-os.llm
           -chardev "socket,id=qa,path=$repo/.local/live-test/qa.sock,server=on,wait=off"
           -device virtserialport,chardev=qa,name=org.agi-os.qa)
    args+=(-drive "file=$iso,media=cdrom,readonly=on,if=none,id=live"
           -device ide-cd,drive=live,bootindex=1
           -drive "file=$repo/.local/live-test-workspace.img,format=raw,if=none,id=workspace"
           -device virtio-blk-pci,drive=workspace,serial=AGIOS_TESTDATA)
else
    args+=(-nic user,model=virtio-net-pci)
fi
if [[ $mode == live && -n ${AGIOS_TEST_CACHE_ISO:-} ]]; then
    [[ -f "$AGIOS_TEST_CACHE_ISO" ]] || { echo 'QA package cache ISO missing'; exit 1; }
    args+=(-drive "file=$AGIOS_TEST_CACHE_ISO,media=cdrom,readonly=on,if=none,id=testcache"
           -device ide-cd,drive=testcache,bus=ide.1)
fi
qemu-system-x86_64 "${args[@]}" > .local/live-test/qemu.log 2>&1 &
qemu_pid=$!
wait "$qemu_pid"
