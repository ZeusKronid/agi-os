import type { ToolGlyph, ToolMark } from './marks'

export type ToolIcon = { mark: ToolMark } | { glyph: ToolGlyph }

export interface Tool {
  id: string
  label: string
  icon: ToolIcon
}

/**
 * Примеры того, что можно назвать словами: окружения, инструменты и просто пожелания. Не каталог.
 * Порядок = порядок в атласе «Your setup»: сказанное в демо разбросано между остальным, а не собрано в ряд.
 */
export const tools: readonly Tool[] = [
  { id: 'btrfs', label: 'Btrfs', icon: { glyph: 'disk' } },
  { id: 'gnome', label: 'GNOME', icon: { mark: 'gnome' } },
  { id: 'no-desktop', label: 'no desktop at all', icon: { glyph: 'terminal' } },
  { id: 'catppuccin', label: 'Catppuccin', icon: { glyph: 'palette' } },
  { id: 'alacritty', label: 'Alacritty', icon: { mark: 'alacritty' } },
  { id: 'steam', label: 'Steam', icon: { mark: 'steam' } },
  { id: 'fish', label: 'fish', icon: { mark: 'fishshell' } },
  { id: 'nvidia', label: 'Nvidia drivers', icon: { mark: 'nvidia' } },
  { id: 'hyprland', label: 'Hyprland', icon: { mark: 'hyprland' } },
  { id: 'firefox', label: 'Firefox', icon: { mark: 'firefox' } },
  { id: 'i3', label: 'i3', icon: { mark: 'i3' } },
  { id: 'dark-theme', label: 'dark theme', icon: { glyph: 'moon' } },
  { id: 'rust', label: 'Rust', icon: { mark: 'rust' } },
  { id: 'luks', label: 'encrypted disk', icon: { glyph: 'lock' } },
  { id: 'neovim', label: 'neovim', icon: { mark: 'neovim' } },
  { id: 'wayland', label: 'Wayland', icon: { mark: 'wayland' } },
  { id: 'zsh', label: 'zsh', icon: { mark: 'zsh' } },
  { id: 'kde', label: 'KDE Plasma', icon: { mark: 'kdeplasma' } },
  { id: 'dotfiles', label: 'my dotfiles', icon: { glyph: 'braces' } },
  { id: 'sway', label: 'Sway', icon: { mark: 'sway' } },
  { id: 'spotify', label: 'Spotify', icon: { mark: 'spotify' } },
  { id: 'docker', label: 'Docker', icon: { mark: 'docker' } },
  { id: 'wallpaper', label: 'matching wallpaper', icon: { glyph: 'image' } },
  { id: 'python', label: 'Python', icon: { mark: 'python' } },
  { id: 'flatpak', label: 'Flatpak', icon: { mark: 'flatpak' } },
  { id: 'xfce', label: 'XFCE', icon: { mark: 'xfce' } },
  { id: 'tmux', label: 'tmux', icon: { mark: 'tmux' } },
  { id: 'gruvbox', label: 'Gruvbox', icon: { glyph: 'palette' } },
  { id: 'obsidian', label: 'Obsidian', icon: { mark: 'obsidian' } },
  { id: 'aur', label: 'AUR helper', icon: { glyph: 'box' } },
  { id: 'waybar', label: 'Waybar', icon: { glyph: 'bar' } },
  { id: 'wine', label: 'Wine & Proton', icon: { mark: 'wine' } },
  { id: 'git', label: 'Git', icon: { mark: 'git' } },
  { id: 'snapshots', label: 'snapshots', icon: { glyph: 'history' } },
  { id: 'tiling', label: 'tiling', icon: { glyph: 'tiles' } },
  { id: 'ghostty', label: 'Ghostty', icon: { mark: 'ghostty' } },
  { id: 'nerd-fonts', label: 'Nerd Fonts', icon: { glyph: 'type' } },
  { id: 'discord', label: 'Discord', icon: { mark: 'discord' } },
  { id: 'node', label: 'Node.js', icon: { mark: 'nodedotjs' } },
  { id: 'audio', label: 'low-latency audio', icon: { glyph: 'audio' } },
  { id: 'obs', label: 'OBS', icon: { mark: 'obsstudio' } },
  { id: 'bluetooth', label: 'Bluetooth', icon: { mark: 'bluetooth' } },
  { id: 'gaming', label: 'gaming', icon: { glyph: 'gamepad' } },
]

/** Те же четыре слова, что в запросе демо в hero: «Hyprland, dark theme, neovim and Docker». Порядок = порядок речи. */
export const spokenToolIds = ['hyprland', 'dark-theme', 'neovim', 'docker'] as const

/** Та же фраза, разбитая на слова для сцены «слушаю»; у слов-инструментов есть `id`. */
export const spokenSentence = [
  { text: 'Hyprland,', id: 'hyprland' },
  { text: 'dark theme,', id: 'dark-theme' },
  { text: 'neovim', id: 'neovim' },
  { text: 'and' },
  { text: 'Docker.', id: 'docker' },
] as const
