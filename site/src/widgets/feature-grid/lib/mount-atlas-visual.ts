import { gsap, REDUCED_MOTION_QUERY } from '@/shared/lib/motion'

import { setups } from '../model/setups'

const all = <T extends Element>(root: Element, selector: string) => Array.from(root.querySelectorAll<T>(selector))

/** Смена набора, мс. */
const CYCLE = 3000

/** Порядок наборов: первый — из демо, дальше перемешано; в следующем круге перемешивается снова, без повтора на стыке. */
function* order(): Generator<number> {
  let last = 0
  yield 0
  for (;;) {
    const rest = setups.map((_, i) => i).filter((i) => i !== last)
    for (let i = rest.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1))
      ;[rest[i], rest[j]] = [rest[j]!, rest[i]!]
    }
    for (const i of rest) {
      last = i
      yield i
    }
  }
}

/**
 * Callback ref (React 19): ролик атласа «Your setup».
 * - Вход во вьюпорт (видна треть): чипы вылетают из центра визуала на свои места, сначала подсвеченные, потом остальные.
 *   Вылет всегда доигрывается до конца; повторяется только после полного ухода из вьюпорта.
 * - Каждые 3 с загорается другой набор из `model/setups` (порядок случайный), подпись в углу называет его. Идёт только пока визуал виден.
 * - Курсор ничего не двигает: единственная реакция на наведение — CSS-hover чипа.
 * - Reduced motion: чипы только проявляются; смена наборов остаётся — это смена цвета.
 * - SSR-разметка показывает атлас с набором из демо: без JavaScript карточка остаётся законченной картинкой.
 */
export function mountAtlasVisual(root: HTMLElement | null): void | (() => void) {
  if (!root) return
  const chips = all<HTMLElement>(root, '[data-chip]')
  const name = root.querySelector<HTMLElement>('[data-setup-name]')
  if (!chips.length || !name) return

  const reduced = window.matchMedia(REDUCED_MOTION_QUERY).matches
  const byId = new Map(chips.filter((chip) => chip.dataset.tool).map((chip) => [chip.dataset.tool!, chip]))

  // До первого входа во вьюпорт чипы скрыты, иначе они мелькнут до вылета.
  gsap.set(chips, { opacity: 0 })

  // Смена набора: атрибут `data-said` переключает заливку, цвет перетекает CSS-переходом (500 мс, ease-theme).
  const sequence = order()
  sequence.next() // первый набор уже в SSR-разметке
  let lit = new Set<string>(setups[0]!.ids)
  const show = (index: number) => {
    const setup = setups[index]!
    lit = new Set(setup.ids)
    byId.forEach((chip, id) => (chip.dataset.said = String(lit.has(id))))
    name.textContent = setup.name
  }
  let cycleTimer: ReturnType<typeof setInterval> | undefined
  const startCycle = () => {
    stopCycle()
    cycleTimer = setInterval(() => show(sequence.next().value as number), CYCLE)
  }
  const stopCycle = () => {
    clearInterval(cycleTimer)
    cycleTimer = undefined
  }

  let tl: gsap.core.Timeline | undefined
  const play = () => {
    tl?.kill()
    const said = chips.filter((chip) => chip.dataset.said === 'true')
    const other = chips.filter((chip) => chip.dataset.said !== 'true')
    tl = gsap.timeline({
      defaults: { ease: 'expo.out', duration: 0.9 },
      onComplete: startCycle,
    })
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

  // Вылет стартует, когда видна треть визуала, и всегда доигрывается до конца: пауза на полпути оставляла чипы
  // друг на друге, если пользователь чуть отскролливал назад. Повтор — только после полного ухода из вьюпорта.
  let played = false
  const observer = new IntersectionObserver(
    (entries) => {
      const entry = entries[entries.length - 1]
      if (!entry) return
      if (!entry.isIntersecting) {
        played = false
        stopCycle()
        return
      }
      if (entry.intersectionRatio >= 0.3 && !played) {
        played = true
        play()
      }
    },
    { threshold: [0, 0.3] },
  )
  observer.observe(root)

  return () => {
    observer.disconnect()
    tl?.kill()
    stopCycle()
  }
}
