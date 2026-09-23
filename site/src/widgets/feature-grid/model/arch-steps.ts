import { tools } from '@/entities/tool'

import type { Setup } from './setups'

/**
 * Что обычно делают руками, чтобы собрать систему на Arch: простыми словами, без команд (DESIGN.md: терминал
 * на сайте не выносим). Честное обобщение, а не инструкция: общие шаги для любой системы, по шагу на каждую
 * вещь из набора и неизбежная уборка после первой перезагрузки. Шаги короткие: список читается одним взглядом.
 */
const BEFORE = [
  'Partition the disk',
  'Install the base system',
  'Set up the bootloader',
  'Create a user and locale',
] as const
const AFTER = 'Fix what broke on reboot'

const byTool: Readonly<Record<string, string>> = {
  hyprland: 'Write hyprland.conf',
  'dark-theme': 'Make GTK and Qt go dark',
  neovim: 'Find a neovim config',
  docker: 'Set up Docker',
  kde: 'Pick Plasma packages',
  steam: 'Enable multilib for Steam',
  nvidia: 'Pick the Nvidia driver',
  wine: 'Set up Wine and Proton',
  gaming: 'Tune it for games',
  discord: 'Install Discord',
  sway: 'Write a Sway config',
  waybar: 'Style Waybar by hand',
  alacritty: 'Configure Alacritty',
  fish: 'Make fish your shell',
  tmux: 'Write a tmux config',
  gruvbox: 'Theme it all in Gruvbox',
  'no-desktop': 'Set up SSH',
  python: 'Set up Python safely',
  git: 'Install and configure Git',
  luks: 'Encrypt the disk',
  snapshots: 'Set up snapshots',
  gnome: 'Install GNOME',
  obs: 'Get OBS working on Wayland',
  obsidian: 'Install Obsidian',
  spotify: 'Find Spotify in the AUR',
  bluetooth: 'Enable Bluetooth',
  wallpaper: 'Find a matching wallpaper',
  i3: 'Write an i3 config',
  rust: 'Install Rust with rustup',
  ghostty: 'Install Ghostty',
  zsh: 'Set up zsh and a prompt',
  'nerd-fonts': 'Fix glyphs with Nerd Fonts',
  dotfiles: 'Bring your dotfiles over',
  xfce: 'Install XFCE',
  firefox: 'Install Firefox',
  catppuccin: 'Theme it all in Catppuccin',
  flatpak: 'Set up Flatpak',
  btrfs: 'Lay out Btrfs subvolumes',
  audio: 'Tune PipeWire latency',
  wayland: 'Force apps onto Wayland',
  tiling: 'Learn the tiling keybindings',
  node: 'Install Node.js',
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
