import { tools } from '@/entities/tool'

import type { Setup } from './setups'

/**
 * Что обычно делают руками, чтобы собрать систему на Arch: простыми словами, без команд (DESIGN.md: терминал
 * на сайте не выносим). Честное обобщение, а не инструкция: общие шаги для любой системы, по шагу на каждую
 * вещь из набора и неизбежная уборка после первой перезагрузки.
 */
const BEFORE = [
  'Partition and format the disk',
  'Install the base system',
  'Set up the bootloader',
  'Create a user, locale and time zone',
] as const
const AFTER = 'Fix whatever broke on the first reboot'

const byTool: Readonly<Record<string, string>> = {
  hyprland: 'Read the Hyprland wiki, write hyprland.conf',
  'dark-theme': 'Make GTK and Qt apps agree on dark',
  neovim: 'Install neovim and a config that works',
  docker: 'Install Docker, enable the service, fix the group',
  kde: 'Pick the right Plasma packages',
  steam: 'Enable multilib for Steam',
  nvidia: 'Choose the right Nvidia driver for your card',
  wine: 'Set up Wine and Proton',
  gaming: 'Tune the system for games',
  discord: 'Install Discord',
  sway: 'Write a Sway config from scratch',
  waybar: 'Style Waybar by hand',
  alacritty: 'Configure Alacritty',
  fish: 'Make fish your shell',
  tmux: 'Write a tmux config',
  gruvbox: 'Theme every app in Gruvbox',
  'no-desktop': 'Skip the desktop, set up SSH',
  python: 'Set up Python without breaking the system one',
  git: 'Install and configure Git',
  luks: 'Encrypt the disk before installing',
  snapshots: 'Set up snapshots you can roll back',
  gnome: 'Install GNOME and its extras',
  obs: 'Get OBS capturing on Wayland',
  obsidian: 'Install Obsidian',
  spotify: 'Find Spotify in the AUR',
  bluetooth: 'Enable Bluetooth and pair devices',
  wallpaper: 'Find a wallpaper that matches the theme',
  i3: 'Write an i3 config',
  rust: 'Install Rust with rustup',
  ghostty: 'Install Ghostty',
  zsh: 'Set up zsh and a prompt',
  'nerd-fonts': 'Install Nerd Fonts and fix missing glyphs',
  dotfiles: 'Bring your dotfiles over',
  xfce: 'Install XFCE and a display manager',
  firefox: 'Install Firefox',
  catppuccin: 'Theme every app in Catppuccin',
  flatpak: 'Set up Flatpak',
  btrfs: 'Lay out Btrfs subvolumes',
  audio: 'Tune PipeWire for low latency',
  wayland: 'Make every app run on Wayland',
  tiling: 'Learn the tiling keybindings',
  node: 'Install Node.js with a version manager',
  aur: 'Install an AUR helper',
}

/** Шаги ручной настройки для набора, по порядку. */
export function archSteps(setup: Setup): string[] {
  return [...BEFORE, ...setup.ids.map((id) => byTool[id]!), AFTER]
}

/** Сколько страниц вики обычно открыто по дороге: по одной на вещь из набора плюс установка, загрузчик и «что сломалось». */
export function wikiPages(setup: Setup): number {
  return setup.ids.length + 3
}

if (import.meta.env.DEV) {
  const known = new Set(tools.map((tool) => tool.id))
  for (const id of Object.keys(byTool)) if (!known.has(id)) throw new Error(`arch-steps: unknown tool "${id}"`)
}
