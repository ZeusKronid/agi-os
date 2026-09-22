import type { ComponentProps } from 'react'

import { revealOnScroll } from '@/shared/lib/motion'

/** Обёртка, плавно проявляющая содержимое при входе во вьюпорт (GSAP ScrollTrigger). */
export function Reveal(props: Omit<ComponentProps<'div'>, 'ref'>) {
  return <div {...props} ref={revealOnScroll} />
}
