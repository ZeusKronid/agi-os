import { gsap, registerScrollTrigger } from '@/shared/lib/motion'

/**
 * Callback ref (React 19): привязывает scaleX узла к прогрессу скролла всего документа.
 * Индикатор следует за скроллом 1:1 (scrub без инерции), поэтому безопасен и при reduced motion.
 * `context.revert()` убивает твин вместе с его ScrollTrigger и возвращает инлайн-стили.
 */
export function mountScrollProgress(node: HTMLElement | null): void | (() => void) {
  if (!node) return

  registerScrollTrigger()

  const context = gsap.context(() => {
    gsap.fromTo(
      node,
      { scaleX: 0 },
      { scaleX: 1, ease: 'none', scrollTrigger: { start: 0, end: 'max', scrub: true } },
    )
  })

  return () => context.revert()
}
