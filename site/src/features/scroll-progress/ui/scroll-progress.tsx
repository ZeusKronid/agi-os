import { mountScrollProgress } from '../lib/mount-scroll-progress'

export function ScrollProgress() {
  return (
    <div
      ref={mountScrollProgress}
      aria-hidden="true"
      // Начальное состояние задано через `transform`, а не через `scale-x-0`: в Tailwind v4 это
      // отдельное CSS-свойство `scale`, которое перемножилось бы с transform от GSAP.
      className="pointer-events-none fixed inset-x-0 top-0 z-50 h-px origin-left bg-accent [transform:scaleX(0)]"
    />
  )
}
