export interface SunburstSpec {
  width: number
  height: number
  cx: number
  cy: number
  radius: number
  rays: number
  /** Полный круг вместо полукруга-восхода. */
  full: boolean
  seed: number
  /** Длины лучей в долях радиуса: каждый четвёртый — длинный, остальные — случайные короткие. */
  long: number
  shortMin: number
  shortMax: number
  /** Радиальное затухание лучей: [начало, конец] в долях радиуса. */
  fade: readonly [number, number]
  strokeWidth: number
  farDots: boolean
}

export interface Ray {
  x1: string
  y1: string
  x2: string
  y2: string
  opacity: string
}

/** Детерминированный ГПСЧ: сервер и клиент обязаны получить одинаковую разметку. */
function mulberry32(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

export function buildRays(spec: SunburstSpec): Ray[] {
  const random = mulberry32(spec.seed)
  const between = (min: number, max: number) => min + (max - min) * random()
  const span = spec.full ? Math.PI * 2 : Math.PI
  const count = spec.full ? spec.rays : spec.rays + 1
  const inner = spec.radius + 8

  return Array.from({ length: count }, (_, index) => {
    const major = index % 4 === 0
    const angle = Math.PI + (span * index) / spec.rays
    const length = spec.radius * (major ? spec.long : between(spec.shortMin, spec.shortMax))
    const opacity = major ? 0.85 : between(0.3, 0.65)
    const cos = Math.cos(angle)
    const sin = Math.sin(angle)
    return {
      x1: (spec.cx + inner * cos).toFixed(1),
      y1: (spec.cy + inner * sin).toFixed(1),
      x2: (spec.cx + (inner + length) * cos).toFixed(1),
      y2: (spec.cy + (inner + length) * sin).toFixed(1),
      opacity: opacity.toFixed(2),
    }
  })
}

/** Точки на дуге восхода, градусы: концы дуги крупнее. */
export const ARC_DOTS = [180, 205, 243, 297, 335, 360] as const
