#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
name=installer
mode=install
firmware=uefi
memory=6144
iso=
headless=false
gl=false
clipboard=true
dev_bridge=false
bridge_model=
while (($#)); do
    case "$1" in
        --name|--mode|--firmware|--memory|--iso|--bridge-model)
            if (($# < 2)); then echo "Missing value: $1" >&2; exit 2; fi
            case "$1" in
                --name) name=$2;; --mode) mode=$2;; --firmware) firmware=$2;;
                --memory) memory=$2;; --iso) iso=$2;; --bridge-model) bridge_model=$2;;
            esac
            shift 2;;
        --dev-bridge) dev_bridge=true; shift;;
        --headless) headless=true; shift;;
        --gl) gl=true; shift;;
        --no-clipboard) clipboard=false; shift;;
        -h|--help)
            cat <<'HELP'
Usage: scripts/run-vm.sh [ISO] [--name SCENARIO] [--mode install|disk]
                         [--firmware uefi|bios] [--memory MiB] [--headless] [--gl]
                         [--no-clipboard] [--dev-bridge] [--bridge-model ID]
Defaults: UEFI, 4 CPUs, 6 GiB RAM, a persistent 64 GiB QCOW2 per scenario.
Install mode selects the newest desktop ISO when no path is supplied.
Disk mode starts the same machine WITHOUT an installation ISO.
Use a new scenario name for a fresh disk. Existing disks are never overwritten.
--gl enables VirtIO OpenGL for compositors needing accelerated graphics.
Graphical runs share the text clipboard through the guest's spice-vdagent.
--no-clipboard disables clipboard sharing; headless runs always disable it.
--dev-bridge connects the installer to host Codex through a private QEMU channel.
--bridge-model overrides the model in the host Codex config. No tokens enter VM.
HELP
            exit 0;;
        -*) echo "Unknown option: $1" >&2; exit 2;;
        *) if [[ -n "$iso" ]]; then echo "Only one ISO is allowed" >&2; exit 2; fi
           iso=$1; shift;;
    esac
done
[[ "$name" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$ ]] || { echo "Invalid scenario name" >&2; exit 2; }
[[ "$mode" == install || "$mode" == disk ]] || { echo "Invalid mode" >&2; exit 2; }
[[ "$firmware" == uefi || "$firmware" == bios ]] || { echo "Invalid firmware" >&2; exit 2; }
[[ "$memory" =~ ^[0-9]+$ ]] && ((memory >= 2048 && memory <= 65536)) || { echo "Invalid RAM size" >&2; exit 2; }
if $dev_bridge && [[ "$mode" != install ]]; then echo "Bridge is only for live installer tests" >&2; exit 2; fi
if [[ -n "$bridge_model" ]] && ! $dev_bridge; then echo "--bridge-model requires --dev-bridge" >&2; exit 2; fi
if $headless && $gl; then echo "--gl requires the graphical display" >&2; exit 2; fi
if ! $headless && $clipboard; then
    backends=$(qemu-system-x86_64 -chardev help)
    if [[ "$backends" != *qemu-vdagent* ]]; then
        echo "This QEMU lacks qemu-vdagent; install a build with clipboard support or use --no-clipboard" >&2; exit 1
    fi
fi
if $gl; then
    devices=$(qemu-system-x86_64 -device help)
    if [[ "$devices" != *'name "virtio-vga-gl"'* ]]; then
        echo "Install qemu-hw-display-virtio-vga-gl to use --gl" >&2; exit 1
    fi
fi
if [[ "$mode" == disk && -n "$iso" ]]; then echo "Disk mode must not attach an ISO" >&2; exit 2; fi
if [[ "$mode" == install ]]; then
    if [[ -z "$iso" ]]; then
        shopt -s nullglob
        images=("$repo_dir"/out/agi-os-desktop-*-x86_64.iso)
        ((${#images[@]})) || { echo "Build an ISO first" >&2; exit 1; }
        iso=${images[${#images[@]}-1]}
    fi
    [[ -f "$iso" ]] || { echo "ISO not found: $iso" >&2; exit 1; }
fi
[[ -r /dev/kvm && -w /dev/kvm ]] || { echo "KVM is not accessible" >&2; exit 1; }
vm_dir="$repo_dir/vm/$name"
disk="$vm_dir/system.qcow2"
if [[ "$mode" == disk && ! -f "$disk" ]]; then echo "No installed disk for $name" >&2; exit 1; fi
if [[ -f "$vm_dir/firmware" && $(<"$vm_dir/firmware") != "$firmware" ]]; then
    echo "Firmware differs from the existing scenario; use its original mode or a new name" >&2; exit 1
fi
if [[ "$firmware" == uefi ]]; then
    code=/usr/share/edk2/x64/OVMF_CODE.4m.fd
    vars=/usr/share/edk2/x64/OVMF_VARS.4m.fd
    [[ -f "$code" && -f "$vars" ]] || { echo "Install edk2-ovmf" >&2; exit 1; }
fi
umask 077
mkdir -p "$vm_dir"
if [[ ! -e "$disk" ]]; then qemu-img create -f qcow2 "$disk" 64G; fi
printf '%s\n' "$firmware" > "$vm_dir/firmware"
disk_bootindex=1
if [[ "$mode" == install ]]; then disk_bootindex=2; fi
args=(-name "AGI OS — $name" -machine q35 -accel kvm -cpu host -m "$memory" -smp 4
      -device qemu-xhci -device usb-tablet
      -drive "file=$disk,format=qcow2,if=none,id=agi-disk"
      -device "virtio-blk-pci,drive=agi-disk,bootindex=$disk_bootindex"
      -nic user,model=virtio-net-pci -qmp "unix:$vm_dir/qmp.sock,server=on,wait=off")
display_options=gtk,show-cursor=on
if $clipboard; then display_options+=,clipboard=on; fi
if $headless; then args+=(-display none -vga std)
elif $gl; then args+=(-display "$display_options,gl=on" -device virtio-vga-gl)
else args+=(-display "$display_options" -vga std); fi
if ! $headless && $clipboard; then
    args+=(-device virtio-serial-pci,id=agi-serial
           -chardev qemu-vdagent,id=agi-vdagent,clipboard=on,mouse=off
           -device virtserialport,bus=agi-serial.0,chardev=agi-vdagent,name=com.redhat.spice.0)
fi
if [[ "$firmware" == uefi ]]; then
    if [[ ! -e "$vm_dir/OVMF_VARS.fd" ]]; then cp "$vars" "$vm_dir/OVMF_VARS.fd"; fi
    args+=(-drive "if=pflash,format=raw,unit=0,readonly=on,file=$code"
           -drive "if=pflash,format=raw,unit=1,file=$vm_dir/OVMF_VARS.fd")
fi
# Explicit device priorities also override stale OVMF boot entries after ISO
# removal. Do not mix bootindex with legacy -boot order/once.
args+=(-boot menu=on)
if [[ "$mode" == install ]]; then
    args+=(-drive "file=$iso,media=cdrom,readonly=on,if=none,id=agi-iso"
           -device ide-cd,drive=agi-iso,bootindex=1)
fi
if $dev_bridge; then
    bridge_dir=$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/agi-bridge.XXXXXXXX")
    bridge_args=(--socket "$bridge_dir/llm.sock")
    if [[ -n "$bridge_model" ]]; then bridge_args+=(--model "$bridge_model"); fi
    python -B "$repo_dir/scripts/dev-bridge.py" "${bridge_args[@]}" > "$vm_dir/bridge.log" 2>&1 &
    bridge_pid=$!
    qemu_pid=
    cleanup_bridge() {
        if [[ -n "$qemu_pid" ]]; then kill "$qemu_pid" 2>/dev/null || true; wait "$qemu_pid" 2>/dev/null || true; fi
        kill "$bridge_pid" 2>/dev/null || true
        wait "$bridge_pid" 2>/dev/null || true
        rm -f "$bridge_dir/llm.sock"
        rmdir "$bridge_dir"
    }
    trap cleanup_bridge EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    for ((attempt=0; attempt<100; attempt++)); do
        [[ -S "$bridge_dir/llm.sock" ]] && break
        if ! kill -0 "$bridge_pid" 2>/dev/null; then echo "Bridge failed; see $vm_dir/bridge.log" >&2; exit 1; fi
        sleep .1
    done
    [[ -S "$bridge_dir/llm.sock" ]] || { echo "Bridge startup timed out" >&2; exit 1; }
    args+=(-device virtio-serial-pci,id=agi-llm-serial
           -chardev "socket,id=agi-llm,path=$bridge_dir/llm.sock"
           -device virtserialport,bus=agi-llm-serial.0,chardev=agi-llm,name=org.agi-os.llm)
    qemu-system-x86_64 "${args[@]}" &
    qemu_pid=$!
    wait "$qemu_pid"
else
    exec qemu-system-x86_64 "${args[@]}"
fi
