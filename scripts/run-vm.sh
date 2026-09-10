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
while (($#)); do
    case "$1" in
        --name|--mode|--firmware|--memory|--iso)
            if (($# < 2)); then echo "Missing value: $1" >&2; exit 2; fi
            case "$1" in
                --name) name=$2;; --mode) mode=$2;; --firmware) firmware=$2;;
                --memory) memory=$2;; --iso) iso=$2;;
            esac
            shift 2;;
        --headless) headless=true; shift;;
        --gl) gl=true; shift;;
        -h|--help)
            cat <<'HELP'
Usage: scripts/run-vm.sh [ISO] [--name SCENARIO] [--mode install|disk]
                         [--firmware uefi|bios] [--memory MiB] [--headless] [--gl]
Defaults: UEFI, 4 CPUs, 6 GiB RAM, a persistent 64 GiB QCOW2 per scenario.
Install mode selects the newest desktop ISO when no path is supplied.
Disk mode starts the same machine WITHOUT an installation ISO.
Use a new scenario name for a fresh disk. Existing disks are never overwritten.
--gl enables VirtIO OpenGL for compositors needing accelerated graphics.
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
if $headless && $gl; then echo "--gl requires the graphical display" >&2; exit 2; fi
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
args=(-name "AGI OS — $name" -machine q35 -accel kvm -cpu host -m "$memory" -smp 4
      -device qemu-xhci -device usb-tablet -drive "file=$disk,format=qcow2,if=virtio"
      -nic user,model=virtio-net-pci -qmp "unix:$vm_dir/qmp.sock,server=on,wait=off")
if $headless; then args+=(-display none -vga std)
elif $gl; then args+=(-display gtk,gl=on -device virtio-vga-gl)
else args+=(-display gtk,show-cursor=on -vga std); fi
if [[ "$firmware" == uefi ]]; then
    if [[ ! -e "$vm_dir/OVMF_VARS.fd" ]]; then cp "$vars" "$vm_dir/OVMF_VARS.fd"; fi
    args+=(-drive "if=pflash,format=raw,unit=0,readonly=on,file=$code"
           -drive "if=pflash,format=raw,unit=1,file=$vm_dir/OVMF_VARS.fd")
fi
if [[ "$mode" == install ]]; then args+=(-cdrom "$iso" -boot menu=on,once=d)
else args+=(-boot menu=on,order=c); fi
exec qemu-system-x86_64 "${args[@]}"
