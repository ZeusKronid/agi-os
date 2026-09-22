import { gsap, MOTION_SAFE_QUERY, registerScrollTrigger } from '@/shared/lib/motion'

/**
 * Callback ref (React 19): восход, разрезанный швом между карточками, встаёт при входе секции во вьюпорт.
 * Дуга дорисовывается слева направо через шов, лучи поднимаются волной вслед за ней, в конце — луч в зазоре.
 * - Сетка, уже видимая при монтировании, не трогается: SSR-разметка и есть финальное состояние.
 * - Анимация создаётся только при `prefers-reduced-motion: no-preference`; `media.revert()` снимает всё.
 * - `pathLength=1`: весь штрих укладывается в 0…1, поэтому `autoRound: false`, иначе GSAP округлит px до целых.
 * - На время входа у лучей выключен CSS-transition (иначе он догоняет каждый кадр GSAP). По завершении
 *   инлайн-стили снимаются, и длиной лучей снова управляет hover через `--sun-extend`.
 */
export function mountSunrise(root: HTMLElement | null): void | (() => void) {
  if (!root) return
  if (root.getBoundingClientRect().top < window.innerHeight) return

  registerScrollTrigger()

  const media = gsap.matchMedia()
  media.add(MOTION_SAFE_QUERY, () => {
    const arcs = root.querySelectorAll('[data-sun-arc]')
    const rays = Array.from(root.querySelectorAll<SVGLineElement>('[data-sun-ray]'))
    const zenith = root.querySelector('[data-sun-zenith]')

    const tl = gsap.timeline({ scrollTrigger: { trigger: root, start: 'top 80%', once: true } })
    tl.fromTo(
      arcs,
      { strokeDashoffset: 1 },
      { strokeDashoffset: 0, duration: 1.5, ease: 'power3.inOut', autoRound: false, clearProps: 'strokeDashoffset' },
      0.25,
    )
    tl.fromTo(
      rays,
      { strokeDashoffset: 1, transition: 'none' },
      {
        strokeDashoffset: (_: number, ray: SVGLineElement) => Number.parseFloat(ray.style.getPropertyValue('--sun-rest')),
        duration: 0.9,
        ease: 'expo.out',
        autoRound: false,
        stagger: (_: number, ray: SVGLineElement) => Number(ray.dataset.sweep) * 0.8,
        clearProps: 'strokeDashoffset,transition',
      },
      0.35,
    )
    if (zenith) {
      tl.fromTo(
        zenith,
        { autoAlpha: 0, scaleY: 0.2, transformOrigin: '50% 100%' },
        { autoAlpha: 1, scaleY: 1, duration: 0.7, ease: 'expo.out', clearProps: 'all' },
        0.95,
      )
    }
  })

  return () => media.revert()
}
