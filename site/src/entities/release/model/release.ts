import { siteConfig } from '@/shared/config'

export interface Release {
  /** Дата сборки из имени образа (`agi-os-<дата>-x86_64.iso`); `null` — релиз ещё не опубликован. */
  version: string | null
  /** SHA-256 образа в нижнем регистре; `null` — сверка на странице выключена, остаётся подсказка. */
  sha256: string | null
  /** Прямая ссылка на ISO. */
  isoUrl: string
  size: string
}

const tag = 'v2026.09.2'
const version = '2026.09.24'

// Новый релиз: обновить tag, version и sha256 (из `agi-os-<дата>-x86_64.iso.sha256` релиза).
export const release: Release = {
  version,
  sha256: 'c8b9c09e95341d75e625a387032ddfbeac17eaf0e06862dbf7d0f5a898138b79',
  isoUrl: `${siteConfig.links.repo}/releases/download/${tag}/agi-os-${version}-x86_64.iso`,
  size: 'about 2 GB',
}

/** Имя файла для показа: до релиза вместо даты — плейсхолдер. */
export function isoDisplayName(value: Release): string {
  return `agi-os-${value.version ?? '<date>'}-x86_64.iso`
}

/** Имя файла для команд: до релиза — маска, которую понимают и shell, и PowerShell. */
export function isoCommandName(value: Release): string {
  return `agi-os-${value.version ?? '*'}-x86_64.iso`
}
