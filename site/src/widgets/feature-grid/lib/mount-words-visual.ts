import { gsap, speechProfile } from '@/shared/lib/motion'

const all = <T extends Element>(root: Element, selector: string) => Array.from(root.querySelectorAll<T>(selector))

interface Refs {
  label: HTMLElement
  mic: HTMLElement
  bars: HTMLElement[]
  words: HTMLElement[]
}

function collect(root: HTMLElement): Refs | null {
  const label = root.querySelector<HTMLElement>('[data-label]')
  const mic = root.querySelector<HTMLElement>('[data-mic]')
  if (!label || !mic) return null
  return {
    label,
    mic,
    // На мобильном каждый второй столбик скрыт CSS — анимируем только видимые.
    bars: all<HTMLElement>(root, '[data-wave] > i').filter((bar) => bar.offsetWidth > 0),
    words: all<HTMLElement>(root, '[data-word]'),
  }
}

/** Ролик: 0,4 с тишины → волна 3,2 с → пауза со сказанной фразой → схлопывание → 0,6 с пустоты → снова. */
function build(refs: Refs): gsap.core.Timeline {
  const { label, mic, bars, words } = refs
  const N = bars.length

  // Амплитуды и моменты «дослушано» — общий профиль речи (`shared/lib/motion/speech`).
  const { amplitude, clusters, heardAt } = speechProfile(N)

  // Схлопывание волны: каждый столбик едет к центру дорожки.
  const waveRect = bars[0]?.parentElement?.getBoundingClientRect()
  const collapseX = bars.map((bar) => {
    if (!waveRect) return 0
    const rect = bar.getBoundingClientRect()
    return waveRect.left + waveRect.width / 2 - (rect.left + rect.width / 2)
  })

  // force3D: false — иначе GSAP на время твина переводит каждый из 84 столбиков в отдельный слой композитора.
  // Состояния (`data-*`) меняются через `set({ attr })`, а не `call()`: перемотка назад честно возвращает прежние значения.
  const tl = gsap.timeline({ repeat: -1, paused: true, defaults: { ease: 'expo.out', force3D: false } })

  // Сброс в начале каждого цикла.
  tl.set(bars, { scaleY: 0.04, opacity: 1, x: 0, attr: { 'data-hit': 'false' } })
  tl.set(words, { opacity: 0, y: 4, attr: { 'data-hit': 'false' } })
  tl.set(mic, { attr: { 'data-on': 'true' } })
  tl.set(label, { attr: { 'data-state': 'listening' } })

  // Listening: волна слева направо, кластеры краснеют, фраза набирается по словам.
  bars.forEach((bar, i) => tl.to(bar, { scaleY: amplitude[i], duration: 0.4, ease: 'power3.out' }, 0.4 + (i / N) * 3.2))
  clusters.forEach((cluster, k) =>
    tl.set(
      cluster.map((i) => bars[i]!),
      { attr: { 'data-hit': 'true' } },
      heardAt[k],
    ),
  )
  let spoken = 0
  words.forEach((word) => {
    const isTool = !!word.dataset.tool
    const at = isTool ? (heardAt[spoken++] ?? 0) : (heardAt[2] ?? 0) + 0.3
    tl.to(word, { opacity: 1, y: 0, duration: 0.45 }, at)
    if (isTool) tl.set(word, { attr: { 'data-hit': 'true' } }, at + 0.08)
  })

  // Got it: микрофон гаснет, фраза остаётся висеть, потом уходит вместе с волной.
  tl.set(mic, { attr: { 'data-on': 'false' } }, 3.9)
  tl.set(label, { attr: { 'data-state': 'heard' } }, 3.9)
  tl.to(words, { opacity: 0, y: -4, duration: 0.35, ease: 'power1.in' }, 5.7)
  bars.forEach((bar, i) =>
    tl.to(bar, { x: collapseX[i], scaleY: 0.04, opacity: 0, duration: 0.55, ease: 'power3.in' }, 5.65 + Math.abs(i / N - 0.5) * 0.15),
  )
  tl.to(label, { duration: 0.6 }, 6.4)

  return tl
}

/**
 * Callback ref (React 19): ролик «слушаю» для карточки «Say it in words».
 * - Таймлайн GSAP с повтором; идёт только пока визуал виден, встаёт на паузу при фокусе внутри.
 * - Клик по микрофону запускает ролик заново.
 * - Схлопывание волны измеряется из раскладки, поэтому при ресайзе и после загрузки шрифтов таймлайн собирается заново.
 * - SSR-разметка показывает фразу дослушанной: без JavaScript карточка остаётся законченной картинкой.
 */
export function mountWordsVisual(root: HTMLElement | null): void | (() => void) {
  if (!root) return
  const refs = collect(root)
  if (!refs) return

  let visible = false
  let held = false
  let tl = build(refs)

  const sync = () => {
    if (visible && !held) tl.play()
    else tl.pause()
  }
  // Пауза только по фокусу внутри (клавиатура). Наведение ролик не останавливает: это видео, а не демо с шагами,
  // и остановка по курсору читалась как «фриз».
  const hold = () => {
    held = true
    sync()
  }
  const release = () => {
    held = root.contains(document.activeElement)
    sync()
  }
  const replay = () => tl.restart()

  const rebuild = () => {
    tl.kill()
    const next = collect(root)
    if (!next) return
    Object.assign(refs, next)
    gsap.set([...root.querySelectorAll('[data-wave] > i'), ...refs.words], { clearProps: 'all' })
    tl = build(refs)
    sync()
  }
  let resizeTimer: ReturnType<typeof setTimeout> | undefined
  const onResize = () => {
    clearTimeout(resizeTimer)
    resizeTimer = setTimeout(rebuild, 250)
  }
  let disposed = false
  document.fonts?.ready.then(() => {
    if (!disposed && !visible) rebuild()
  })

  const observer = new IntersectionObserver(
    (entries) => {
      const entry = entries[entries.length - 1]
      if (!entry) return
      const wasVisible = visible
      visible = entry.isIntersecting
      if (visible && !wasVisible) tl.restart()
      sync()
    },
    { threshold: 0.35 },
  )
  observer.observe(root)

  root.addEventListener('focusin', hold)
  root.addEventListener('focusout', release)
  refs.mic.addEventListener('click', replay)
  window.addEventListener('resize', onResize)

  return () => {
    disposed = true
    clearTimeout(resizeTimer)
    observer.disconnect()
    tl.kill()
    root.removeEventListener('focusin', hold)
    root.removeEventListener('focusout', release)
    refs.mic.removeEventListener('click', replay)
    window.removeEventListener('resize', onResize)
  }
}
