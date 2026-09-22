import type { OsId } from '../model/route'

export function detectOs(userAgent: string): OsId {
  if (/Windows/i.test(userAgent)) return 'win'
  if (/Mac OS X|Macintosh/i.test(userAgent) && !/iPhone|iPad/i.test(userAgent)) return 'mac'
  return 'linux'
}
