export type ChecksumResult = 'empty' | 'typing' | 'match' | 'mismatch'

/** Достаёт SHA-256 из вставленного вывода `sha256sum`, `shasum` или `Get-FileHash`. */
export function parseChecksum(text: string): string | null {
  return text.toLowerCase().match(/\b[0-9a-f]{64}\b/)?.[0] ?? null
}

export function compareChecksum(text: string, expected: string): ChecksumResult {
  const value = text.trim()
  if (!value) return 'empty'
  const found = parseChecksum(value)
  if (found) return found === expected.toLowerCase() ? 'match' : 'mismatch'
  // Пока строка короче хэша, человек ещё вставляет или печатает — ошибку не показываем.
  return value.length < 64 ? 'typing' : 'mismatch'
}
