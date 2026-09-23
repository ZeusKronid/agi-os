#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="agi-os"
iso_label="AGIOS_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="AGI OS"
iso_application="AGI OS conversational installer"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
bootmodes=('bios.syslinux'
           'uefi.systemd-boot')
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
airootfs_image_tool_options=('-comp' 'xz' '-Xbcj' 'x86,arm64' '-b' '1M' '-Xdict-size' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')
file_permissions=(
  ["/home/agi"]="1000:1000:755"
  ["/etc/sudoers.d/10-agi-live"]="0:0:440"
  ["/etc/shadow"]="0:0:400"
  ["/usr/local/bin/choose-mirror"]="0:0:755"
  ["/usr/local/bin/agi-installer"]="0:0:755"
)
