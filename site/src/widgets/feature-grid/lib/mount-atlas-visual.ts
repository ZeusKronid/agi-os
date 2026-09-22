import { gsap, REDUCED_MOTION_QUERY } from '@/shared/lib/motion'

const all = <T extends Element>(root: Element, selector: string) => Array.from(root.querySelectorAll<T>(selector))

/**
 * Callback ref (React 19): ролик атласа «Your setup».
 * - Вход во вьюпорт: чипы вылетают из центра визуала на свои места, сначала сказанное, потом остальное; повторяется при каждом входе.
 * - Дальше чипы медленно дрейфуют по вертикали (только при `motion-safe` и с курсором).
 * - Курсор чуть сдвигает поле: сказанное сильнее, остальное слабее. Параллакс живёт на <li>, вылет и дрейф — на чипе.
 * - Reduced motion: чипы только проявляются, дрейфа и параллакса нет.
 * - SSR-разметка показывает атлас целиком: без JavaScript карточка остаётся законченной картинкой.
 */
export function mountAtlasVisual(root: HTMLElement | null): void | (() => void) {
  if (!root) return
  const slots = all<HTMLElement>(root, '[data-chip-slot]')
  const chips = all<HTMLElement>(root, '[data-chip]')
  if (!chips.length) return

  const reduced = window.matchMedia(REDUCED_MOTION_QUERY).matches
  const pointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches
  const said = chips.filter((chip) => chip.dataset.said === 'true')
  const other = chips.filter((chip) => chip.dataset.said !== 'true')

  // До первого входа во вьюпорт чипы скрыты, иначе они мелькнут до вылета.
  gsap.set(chips, { opacity: 0 })

  let tl: gsap.core.Timeline | undefined
  let drift: gsap.core.Tween[] = []

  const stopDrift = () => {
    drift.forEach((tween) => tween.kill())
    drift = []
  }
  const startDrift = () => {
    if (reduced || !pointer) return
    drift = chips.map((chip, i) =>
      gsap.to(chip, {
        y: i % 2 ? 4 : -4,
        duration: 2.4 + (i % 5) * 0.3,
        ease: 'sine.inOut',
        yoyo: true,
        repeat: -1,
        delay: (i % 7) * 0.2,
      }),
    )
  }

  const play = () => {
    tl?.kill()
    stopDrift()
    tl = gsap.timeline({ defaults: { ease: 'expo.out', duration: 0.9 }, onComplete: startDrift })
    if (reduced) {
      tl.fromTo(said, { opacity: 0 }, { opacity: 1, duration: 0.5, stagger: 0.06 }, 0)
      tl.fromTo(other, { opacity: 0 }, { opacity: 1, duration: 0.5, stagger: 0.02 }, 0.3)
      return
    }
    // Старт вылета — центр визуала; цели измеряются из финальной раскладки прямо перед запуском.
    const rootRect = root.getBoundingClientRect()
    const from = (chip: HTMLElement) => {
      const rect = chip.getBoundingClientRect()
      return {
        x: rootRect.left + rootRect.width / 2 - (rect.left + rect.width / 2),
        y: rootRect.top + rootRect.height / 2 - (rect.top + rect.height / 2),
      }
    }
    gsap.set(chips, { x: 0, y: 0, scale: 1 })
    said.forEach((chip, i) => tl!.fromTo(chip, { ...from(chip), scale: 0.4, opacity: 0 }, { x: 0, y: 0, scale: 1, opacity: 1 }, 0.05 + i * 0.09))
    other.forEach((chip, i) => tl!.fromTo(chip, { ...from(chip), scale: 0.4, opacity: 0 }, { x: 0, y: 0, scale: 1, opacity: 1 }, 0.45 + i * 0.035))
  }

  let visible = false
  const observer = new IntersectionObserver(
    (entries) => {
      const entry = entries[entries.length - 1]
      if (!entry) return
      const wasVisible = visible
      visible = entry.isIntersecting
      if (visible && !wasVisible) play()
      if (!visible) {
        tl?.pause()
        stopDrift()
      }
    },
    { threshold: 0.3 },
  )
  observer.observe(root)

  // Параллакс: геометрия читается один раз на вход курсора, а не на каждый pointermove.
  const slotX = slots.map((slot) => gsap.quickTo(slot, 'x', { duration: 0.7, ease: 'power3' }))
  const slotY = slots.map((slot) => gsap.quickTo(slot, 'y', { duration: 0.7, ease: 'power3' }))
  const strength = slots.map((slot) => (slot.querySelector('[data-chip]')?.getAttribute('data-said') === 'true' ? 1 : 0.5))
  let rect: DOMRect | undefined
  const onEnter = () => {
    rect = root.getBoundingClientRect()
  }
  const onMove = (event: PointerEvent) => {
    if (reduced || !pointer || !rect) return
    const px = (event.clientX - rect.left) / rect.width - 0.5
    const py = (event.clientY - rect.top) / rect.height - 0.5
    slots.forEach((_, i) => {
      slotX[i]!(px * 12 * strength[i]!)
      slotY[i]!(py * 8 * strength[i]!)
    })
  }
  const onLeave = () => {
    rect = undefined
    slots.forEach((_, i) => {
      slotX[i]!(0)
      slotY[i]!(0)
    })
  }

  root.addEventListener('pointerenter', onEnter)
  root.addEventListener('pointermove', onMove)
  root.addEventListener('pointerleave', onLeave)

  return () => {
    observer.disconnect()
    tl?.kill()
    stopDrift()
    root.removeEventListener('pointerenter', onEnter)
    root.removeEventListener('pointermove', onMove)
    root.removeEventListener('pointerleave', onLeave)
  }
}
