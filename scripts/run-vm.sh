#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
iso=${1:-"$repo_dir/out/agi-os-desktop-2026.09.09-x86_64.iso"}
vm_dir="$repo_dir/vm"
disk="$vm_dir/agi-os-desktop.qcow2"

if [[ ! -f "$iso" ]]; then
    echo "ISO not found: $iso" >&2
    exit 1
fi
mkdir -p "$vm_dir"
if [[ ! -e "$disk" ]]; then
    qemu-img create -f qcow2 "$disk" 64G
fi

exec qemu-system-x86_64 \
    -name 'AGI OS — XFCE + Firefox' \
    -accel kvm -cpu host -m 4096 -smp 4 \
    -display gtk,show-cursor=on \
    -vga std -device qemu-xhci -device usb-tablet \
    -drive "file=$disk,format=qcow2,if=virtio" \
    -cdrom "$iso" -boot menu=on,once=d \
    -nic user,model=virtio-net-pci
