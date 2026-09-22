import Lenis from 'lenis'

import { gsap, registerScrollTrigger, ScrollTrigger } from './gsap'
import { REDUCED_MOTION_QUERY } from './media'

// Значения GSAP по умолчанию — возвращаем их при остановке Lenis.
const GSAP_LAG_THRESHOLD = 500
const GSAP_LAG_ADJUSTED = 33

/** Запускает Lenis на общем с GSAP тикере и возвращает полную очистку. */
function startSmoothScroll(): () => void {
  registerScrollTrigger()

  const lenis = new Lenis({ autoRaf: false, anchors: true })
  const onTick = (time: number) => lenis.raf(time * 1000)

  lenis.on('scroll', ScrollTrigger.update)
  gsap.ticker.add(onTick)
  gsap.ticker.lagSmoothing(0)

  return () => {
    gsap.ticker.remove(onTick)
    gsap.ticker.lagSmoothing(GSAP_LAG_THRESHOLD, GSAP_LAG_ADJUSTED)
    lenis.off('scroll', ScrollTrigger.update)
    lenis.destroy()
  }
}

/**
 * Callback ref (React 19): настройка при монтировании узла, очистка — в возвращаемой функции.
 * Сам узел не используется: Lenis скроллит window, узел лишь задаёт жизненный цикл.
 * При `prefers-reduced-motion: reduce` Lenis не создаётся вовсе — остаётся нативный скролл;
 * смена системной настройки на лету обрабатывается слушателем media query.
 *
 * Ссылка на функцию стабильна (уровень модуля), поэтому React не перезапускает её на ререндерах.
 */
export function mountSmoothScroll(node: HTMLElement | null): void | (() => void) {
  if (!node) return

  const reducedMotion = window.matchMedia(REDUCED_MOTION_QUERY)
  let stop = reducedMotion.matches ? undefined : startSmoothScroll()

  const onPreferenceChange = () => {
    stop?.()
    stop = reducedMotion.matches ? undefined : startSmoothScroll()
  }
  reducedMotion.addEventListener('change', onPreferenceChange)

  return () => {
    reducedMotion.removeEventListener('change', onPreferenceChange)
    stop?.()
  }
}
