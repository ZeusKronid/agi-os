import { gsap, registerScrollTrigger } from './gsap'
import { MOTION_SAFE_QUERY } from './media'

/**
 * Callback ref (React 19): плавное появление узла при входе во вьюпорт.
 * - Контент, уже видимый при монтировании, не трогаем — иначе SSR-разметка мигнёт при гидрации.
 * - Анимация создаётся только при `prefers-reduced-motion: no-preference`;
 *   `matchMedia.revert()` убивает твин и его ScrollTrigger и возвращает инлайн-стили.
 */
export function revealOnScroll(node: HTMLElement | null): void | (() => void) {
  if (!node) return
  if (node.getBoundingClientRect().top < window.innerHeight) return

  registerScrollTrigger()

  const media = gsap.matchMedia()
  media.add(MOTION_SAFE_QUERY, () => {
    gsap.from(node, {
      autoAlpha: 0,
      y: 32,
      duration: 0.9,
      ease: 'expo.out',
      scrollTrigger: { trigger: node, start: 'top 85%', once: true },
    })
  })

  return () => media.revert()
}
