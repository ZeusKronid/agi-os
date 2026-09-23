import { gsap, MOTION_SAFE_QUERY, registerScrollTrigger } from '@/shared/lib/motion'
import { mountLiveSun } from '@/shared/ui/sunburst'

/**
 * Насколько солнце садится к концу страницы: доля высоты восхода до горизонта (14% ≈ 0.3 радиуса).
 * Глубже нельзя: сцена рассчитана под лучи, и севшее солнце оставляло бы пустоту между ссылками и лучами.
 */
const SINK_PERCENT = 14
/** Во сколько раз укорачиваются лучи к концу заката. */
const RAYS_AT_DUSK = 0.75

/**
 * Callback ref (React 19) на футер: закат. Страница открывается восходом в hero и закрывается здесь.
 * - Живой восход (мерцание, линза к курсору, дыхание) — тот же `mountLiveSun`, что в hero.
 * - Закат ведёт скролл (ScrollTrigger scrub): от момента, когда верх футера на 65% экрана, до конца
 *   страницы солнце опускается за буквы-силуэты wordmark, а лучи укорачиваются. Анимируются только
 *   transform обёртки восхода и слоя лучей — их ведёт композитор.
 * - Без `prefers-reduced-motion: no-preference` солнце просто стоит над горизонтом.
 */
export function mountSunset(root: HTMLElement | null): void | (() => void) {
  if (!root) return
  const sun = root.querySelector<HTMLElement>('[data-sun-live]')
  const rays = root.querySelector<HTMLElement>('[data-sun-rays]')
  if (!sun || !rays) return

  registerScrollTrigger()
  const media = gsap.matchMedia()
  media.add(MOTION_SAFE_QUERY, () => {
    gsap
      .timeline({ scrollTrigger: { trigger: root, start: 'top 65%', end: 'bottom bottom', scrub: 0.6 } })
      .to(sun, { yPercent: SINK_PERCENT, ease: 'power2.inOut' }, 0)
      .to(rays, { scale: RAYS_AT_DUSK, ease: 'power2.inOut' }, 0)
  })
  const stopLiveSun = mountLiveSun(root)

  return () => {
    media.revert()
    stopLiveSun?.()
  }
}
