import type { ToolGlyph, ToolMark } from './marks'

export type ToolIcon = { mark: ToolMark } | { glyph: ToolGlyph }

export interface Tool {
  id: string
  label: string
  icon: ToolIcon
}

/** Примеры того, что можно назвать словами: окружения, инструменты и просто пожелания. Не каталог. */
export const tools: readonly Tool[] = [
  { id: 'hyprland', label: 'Hyprland', icon: { mark: 'hyprland' } },
  { id: 'dark-theme', label: 'dark theme', icon: { glyph: 'moon' } },
  { id: 'kde', label: 'KDE Plasma', icon: { mark: 'kdeplasma' } },
  { id: 'sway', label: 'Sway', icon: { mark: 'sway' } },
  { id: 'waybar', label: 'Waybar', icon: { glyph: 'bar' } },
  { id: 'neovim', label: 'neovim', icon: { mark: 'neovim' } },
  { id: 'docker', label: 'Docker', icon: { mark: 'docker' } },
  { id: 'zsh', label: 'zsh', icon: { mark: 'zsh' } },
  { id: 'btrfs', label: 'Btrfs', icon: { glyph: 'disk' } },
  { id: 'xfce', label: 'XFCE', icon: { mark: 'xfce' } },
  { id: 'no-desktop', label: 'no desktop at all', icon: { glyph: 'terminal' } },
  { id: 'python', label: 'Python', icon: { mark: 'python' } },
  { id: 'steam', label: 'Steam', icon: { mark: 'steam' } },
  { id: 'tiling', label: 'tiling', icon: { glyph: 'tiles' } },
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
