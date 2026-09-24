/** Доли ширины волны, занятые четырьмя словами речи; между ними тишина. */
export const SPEECH_SPANS = [
  [0.05, 0.24],
  [0.3, 0.5],
  [0.56, 0.71],
  [0.77, 0.95],
] as const

export interface SpeechProfile {
  /** Целевая высота каждого столбика (scaleY): внутри слова — «горб», между словами — шум. */
  amplitude: number[]
  /** Индексы столбиков каждого слова. */
  clusters: number[][]
  /** Момент (с от старта волны), когда слово дослушано: конец кластера плюс небольшая задержка. */
  heardAt: number[]
}

const rnd = (min: number, max: number) => min + Math.random() * (max - min)

/**
 * Профиль волны речи для `count` столбиков. Разбег волны слева направо длится `sweep` секунд
 * и начинается в `lead`; одинаков для визуала «Say it in words» и демо в hero.
 */
export function speechProfile(count: number, sweep = 3.2, lead = 0.4): SpeechProfile {
  const amplitude = Array.from({ length: count }, (_, i) => {
    const u = i / count
    for (const [from, to] of SPEECH_SPANS) {
      if (u >= from && u <= to) return 0.3 + Math.sin(Math.PI * ((u - from) / (to - from))) * rnd(0.45, 0.7)
    }
    return rnd(0.06, 0.14)
  })
  const clusters = SPEECH_SPANS.map(([from, to]) =>
    Array.from({ length: count }, (_, i) => i).filter((i) => i / count >= from && i / count <= to),
  )
  const heardAt = clusters.map((cluster) => lead + ((cluster[cluster.length - 1] ?? 0) / count) * sweep + 0.18)
  return { amplitude, clusters, heardAt }
}
