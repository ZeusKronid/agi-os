/** Что запрос делает с мини-столом в карточке «Try it live first». */
export type LiveEffect = 'dark' | 'bar' | 'rice' | 'bouncy' | 'reset'

export interface LiveWord {
  text: string
  /** Слово-инструмент: курсив кораллом, как в hero. */
  hot?: true
}

export interface LiveRequest {
  words: readonly LiveWord[]
  effect: LiveEffect
}

/**
 * Пять запросов по кругу. Изменения накапливаются, как в настоящем диалоге, последний возвращает всё назад.
 * В покое стол светлый: это результат последнего запроса, поэтому первый же делает его тёмным,
 * и большую часть цикла стол остаётся тёмным.
 */
export const liveRequests = [
  { words: [{ text: 'dark', hot: true }, { text: 'theme', hot: true }], effect: 'dark' },
  { words: [{ text: 'hide the' }, { text: 'top', hot: true }, { text: 'bar', hot: true }], effect: 'bar' },
  { words: [{ text: 'rounder,', hot: true }, { text: 'more' }, { text: 'gaps', hot: true }], effect: 'rice' },
  { words: [{ text: 'bouncy', hot: true }, { text: 'windows' }], effect: 'bouncy' },
  { words: [{ text: 'light', hot: true }, { text: 'theme,', hot: true }, { text: 'bar' }, { text: 'back', hot: true }], effect: 'reset' },
] as const satisfies readonly LiveRequest[]

/** Запрос, результат которого показан в покое (SSR-разметка). */
export const restRequestIndex = liveRequests.length - 1

export const liveWindows = ['terminal', 'files', 'editor'] as const
export type LiveWindow = (typeof liveWindows)[number]
