import { spokenToolIds, tools } from '@/entities/tool'

export interface Setup {
  /** Подпись вкладки набора в карточке «Arch was never this easy». Коротко: все вкладки — в один ряд. */
  name: string
  ids: readonly string[]
}

/**
 * Наборы для сравнения «обычный Arch против одной фразы»: не случайные вещи, а системы, которые правда собирают.
 * Первый — тот же, что в демо в hero.
 */
export const setups: readonly Setup[] = [
  { name: 'from the demo', ids: spokenToolIds },
  { name: 'gaming rig', ids: ['kde', 'steam', 'nvidia', 'wine', 'gaming', 'discord'] },
  { name: 'tiling minimalist', ids: ['sway', 'waybar', 'alacritty', 'fish', 'tmux', 'gruvbox'] },
  { name: 'server, no desktop', ids: ['no-desktop', 'docker', 'python', 'git', 'luks', 'snapshots'] },
  { name: 'creator desk', ids: ['gnome', 'obs', 'obsidian', 'spotify', 'bluetooth', 'wallpaper'] },
  { name: 'rust workstation', ids: ['i3', 'rust', 'ghostty', 'zsh', 'nerd-fonts', 'dotfiles'] },
  { name: 'cozy laptop', ids: ['xfce', 'firefox', 'catppuccin', 'flatpak', 'btrfs', 'audio'] },
  { name: 'wayland from scratch', ids: ['wayland', 'hyprland', 'waybar', 'tiling', 'node', 'aur'] },
]

if (import.meta.env.DEV) {
  const known = new Set(tools.map((tool) => tool.id))
  for (const setup of setups) for (const id of setup.ids) if (!known.has(id)) throw new Error(`setups: unknown tool "${id}" in "${setup.name}"`)
}
