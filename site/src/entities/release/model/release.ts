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

// TODO: заполнить version, sha256 и isoUrl, когда появится страница релиза с ISO.
export const release: Release = {
  version: null,
  sha256: null,
  isoUrl: siteConfig.links.download,
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
