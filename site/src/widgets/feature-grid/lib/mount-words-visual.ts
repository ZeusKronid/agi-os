import { gsap, speechProfile } from '@/shared/lib/motion'

const all = <T extends Element>(root: Element, selector: string) => Array.from(root.querySelectorAll<T>(selector))

interface Refs {
  scenes: HTMLElement[]
  mic: HTMLElement
  bars: HTMLElement[]
  words: HTMLElement[]
  labelDot: HTMLElement
  labelText: HTMLElement
  ring: SVGElement
  progress: SVGElement
  ticks: SVGElement[]
  check: SVGElement
  checkPath: SVGElement
  reads: HTMLElement[]
  readChecks: SVGElement[]
  done: HTMLElement
  saidLayer: HTMLElement
  otherLayer: HTMLElement
  saidChips: HTMLElement[]
  otherChips: HTMLElement[]
}

function collect(root: HTMLElement): Refs | null {
  const one = <T extends Element>(selector: string) => root.querySelector<T>(selector)
  const scenes = all<HTMLElement>(root, '[data-scene]')
  const mic = one<HTMLElement>('[data-mic]')
  const labelDot = one<HTMLElement>('[data-label-dot]')
  const labelText = one<HTMLElement>('[data-label-text]')
  const ring = one<SVGElement>('[data-ring]')
  const progress = one<SVGElement>('[data-progress]')
  const check = one<SVGElement>('[data-check]')
  const checkPath = check?.querySelector<SVGElement>('path')
  const done = one<HTMLElement>('[data-done]')
  const saidLayer = one<HTMLElement>('[data-layer="said"]')
  const otherLayer = one<HTMLElement>('[data-layer="other"]')
  if (scenes.length !== 3 || !mic || !labelDot || !labelText || !ring || !progress || !check || !checkPath || !done || !saidLayer || !otherLayer) {
    return null
  }
  return {
    scenes,
    mic,
    // На мобильном каждый второй столбик скрыт CSS — анимируем только видимые.
    bars: all<HTMLElement>(root, '[data-wave] > i').filter((bar) => bar.offsetWidth > 0),
    words: all<HTMLElement>(root, '[data-word]'),
    labelDot,
    labelText,
    ring,
    progress,
    ticks: all<SVGElement>(root, '[data-tick]'),
    check,
    checkPath,
    reads: all<HTMLElement>(root, '[data-read]'),
    readChecks: all<SVGElement>(root, '[data-read-check]'),
    done,
    saidLayer,
    otherLayer,
    saidChips: all<HTMLElement>(saidLayer, '[data-chip]'),
    otherChips: all<HTMLElement>(otherLayer, '[data-chip]'),
  }
}

/** Смена сцены как в демо hero: уход 150 мс, вход 400 мс. */
function cut(tl: gsap.core.Timeline, scenes: HTMLElement[], index: number, at: number) {
  scenes.forEach((scene, i) => {
    if (i !== index) tl.to(scene, { autoAlpha: 0, y: -6, duration: 0.15, ease: 'power1.in' }, at)
  })
  tl.fromTo(scenes[index]!, { autoAlpha: 0, y: 8 }, { autoAlpha: 1, y: 0, duration: 0.4, ease: 'expo.out' }, at + 0.15)
}

function build(root: HTMLElement, refs: Refs, compact: boolean): gsap.core.Timeline {
  const { scenes, mic, bars, words, labelDot, labelText, ring, progress, ticks, check, checkPath, reads, readChecks, done } = refs
  const chips = [...refs.saidChips, ...refs.otherChips]
  const N = bars.length

  const setLabel = (text: string, live: boolean) => {
    labelText.textContent = text
    labelDot.dataset.live = String(live)
  }

  // Амплитуды и моменты «дослушано» — общий профиль речи (`shared/lib/motion/speech`).
  const { amplitude, clusters, heardAt } = speechProfile(N)

  // Схлопывание волны: каждый столбик едет к центру дорожки.
  const waveRect = bars[0]!.parentElement!.getBoundingClientRect()
  const collapseX = bars.map((bar) => {
    const rect = bar.getBoundingClientRect()
    return waveRect.left + waveRect.width / 2 - (rect.left + rect.width / 2)
  })
  // Вылет чипов: измерены в финальной раскладке (созвездие или поток), старт — центр визуала.
  const rootRect = root.getBoundingClientRect()
  const flyFrom = chips.map((chip) => {
    const rect = chip.getBoundingClientRect()
    return { x: rootRect.left + rootRect.width / 2 - (rect.left + rect.width / 2), y: rootRect.top + rootRect.height / 2 - (rect.top + rect.height / 2) }
  })

  // force3D: false — иначе GSAP на время твина переводит каждый из 84 столбиков в отдельный слой композитора,
  // и слои создаются/уничтожаются каждые ~40 мс. Крупные узлы (сцены, чипы, кольцо) подняты в слой заранее через will-change.
  const tl = gsap.timeline({ repeat: -1, paused: true, defaults: { ease: 'expo.out', force3D: false } })

  // Сброс в начале каждого цикла.
  tl.set(scenes, { autoAlpha: 0 })
  tl.set(bars, { scaleY: 0.04, opacity: 1, x: 0 })
  tl.set(words, { opacity: 0, y: 4 })
  tl.set(ring, { rotation: -90, scale: 1, opacity: 1, transformOrigin: '50% 50%' })
  tl.set(progress, { strokeDashoffset: 201 })
  tl.set(ticks, { opacity: 1 })
  tl.set(check, { opacity: 1, scale: 1 })
  tl.set(checkPath, { strokeDashoffset: 34 })
  tl.set(reads, { opacity: 0, y: 4, scale: 1 })
  tl.set(readChecks, { opacity: 0, scale: 0.6 })
  tl.set(done, { opacity: 0 })
  tl.call(() => {
    bars.forEach((bar) => (bar.dataset.hit = 'false'))
    words.forEach((word) => (word.dataset.hit = 'false'))
    mic.dataset.on = 'true'
    setLabel('listening', true)
  })

  // 01 · Listening: волна слева направо, кластеры краснеют, фраза набирается по словам.
  cut(tl, scenes, 0, 0)
  bars.forEach((bar, i) => tl.to(bar, { scaleY: amplitude[i], duration: 0.4, ease: 'power3.out' }, 0.4 + (i / N) * 3.2))
  clusters.forEach((cluster, k) => tl.call(() => cluster.forEach((i) => (bars[i]!.dataset.hit = 'true')), undefined, heardAt[k]))
  let spoken = 0
  words.forEach((word) => {
    const isTool = !!word.dataset.tool
    const at = isTool ? (heardAt[spoken++] ?? 0) : (heardAt[2] ?? 0) + 0.3
    tl.to(word, { opacity: 1, y: 0, duration: 0.45 }, at)
    if (isTool) tl.call(() => (word.dataset.hit = 'true'), undefined, at + 0.08)
  })
  tl.call(() => (mic.dataset.on = 'false'), undefined, 3.9)
  tl.to(words, { opacity: 0, duration: 0.35, ease: 'power1.in' }, 4.05)
  bars.forEach((bar, i) =>
    tl.to(bar, { x: collapseX[i], scaleY: 0.04, opacity: 0, duration: 0.55, ease: 'power3.in' }, 4.0 + Math.abs(i / N - 0.5) * 0.15),
  )

  // 02 · Thinking: кольцо вращается и дорисовывается, слова загораются.
  tl.call(() => setLabel('thinking', true), undefined, 4.4)
  cut(tl, scenes, 1, 4.45)
  tl.to(ring, { rotation: 270, duration: 2.6, ease: 'none' }, 4.6)
  tl.to(progress, { strokeDashoffset: 0, duration: 2.4, ease: 'power2.inOut' }, 4.7)
  reads.forEach((read, i) => tl.to(read, { opacity: 1, y: 0, duration: 0.4 }, 5.0 + i * 0.45))

  // Installed: деления гаснут, галочка рисуется внутри кольца, слова получают галочки.
  tl.call(() => setLabel('installed', false), undefined, 7.15)
  tl.to(ticks, { opacity: 0, duration: 0.25, stagger: { each: 0.006, from: 'random' } }, 7.1)
  tl.fromTo(ring, { scale: 1 }, { scale: 1.06, duration: 0.18, ease: 'power2.out', yoyo: true, repeat: 1 }, 7.15)
  tl.to(checkPath, { strokeDashoffset: 0, duration: 0.4, ease: 'power2.out' }, 7.25)
  tl.to(readChecks, { opacity: 1, scale: 1, duration: 0.35, stagger: 0.09 }, 7.45)
  tl.to(done, { opacity: 1, duration: 0.4 }, 7.8)

  // 03 · Your setup: чипы вылетают из центра кольца в созвездие.
  tl.to([ring, check, reads, done], { opacity: 0, scale: 0.85, duration: 0.3, ease: 'power1.in' }, 9.2)
  tl.call(() => setLabel('your setup', false), undefined, 9.4)
  tl.set(scenes[2]!, { autoAlpha: 1, y: 0 }, 9.4)
  tl.set(scenes[1]!, { autoAlpha: 0 }, 9.55)
  chips.forEach((chip, i) => tl.set(chip, { ...flyFrom[i], scale: 0.4, opacity: 0 }, 9.4))
  tl.to(refs.saidChips, { x: 0, y: 0, scale: 1, opacity: 1, duration: 0.9, stagger: 0.08 }, 9.45)
  tl.to(refs.otherChips, { x: 0, y: 0, scale: 1, opacity: 1, duration: 0.9, stagger: 0.05 }, 9.9)
  if (!compact) tl.to(chips, { y: 4, duration: 2.2, ease: 'sine.inOut', yoyo: true, repeat: 1, stagger: { each: 0.1 } }, 10.9)
  tl.to([scenes[2]!, labelText.parentElement!], { autoAlpha: 0, duration: 0.5, ease: 'power1.in' }, 15.1)
  tl.set(labelText.parentElement!, { autoAlpha: 1 }, 15.6)
  tl.to(root, { duration: 0.2 }, 15.7)

  return tl
}

/**
 * Callback ref (React 19): ролик из трёх сцен для карточки «Say it in words».
 * - Таймлайн GSAP с повтором; идёт только пока визуал виден, встаёт на паузу при фокусе внутри.
 * - Клик по микрофону запускает ролик заново. На десктопе созвездие чуть следует за курсором.
 * - Позиции для вылета чипов измеряются из финальной раскладки, поэтому при ресайзе таймлайн собирается заново.
 * - SSR-разметка показывает третью сцену: без JavaScript карточка остаётся законченной картинкой.
 */
export function mountWordsVisual(root: HTMLElement | null): void | (() => void) {
  if (!root) return
  const refs = collect(root)
  if (!refs) return

  let visible = false
  let held = false
  let compact = refs.bars.length < root.querySelectorAll('[data-wave] > i').length
  let tl = build(root, refs, compact)

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

  // Параллакс созвездия: сказанное сдвигается сильнее, остальное слабее.
  // Геометрия читается один раз на вход курсора: getBoundingClientRect на каждом pointermove
  // форсировал бы layout между кадрами таймлайна.
  const saidX = gsap.quickTo(refs.saidLayer, 'x', { duration: 0.6, ease: 'power3' })
  const saidY = gsap.quickTo(refs.saidLayer, 'y', { duration: 0.6, ease: 'power3' })
  const otherX = gsap.quickTo(refs.otherLayer, 'x', { duration: 0.8, ease: 'power3' })
  const otherY = gsap.quickTo(refs.otherLayer, 'y', { duration: 0.8, ease: 'power3' })
  let rect: DOMRect | undefined
  const onEnter = () => {
    rect = root.getBoundingClientRect()
  }
  const onMove = (event: PointerEvent) => {
    if (compact || !rect) return
    const px = (event.clientX - rect.left) / rect.width - 0.5
    const py = (event.clientY - rect.top) / rect.height - 0.5
    saidX(px * 12)
    saidY(py * 8)
    otherX(px * 6)
    otherY(py * 4)
  }
  const onLeave = () => {
    rect = undefined
    saidX(0)
    saidY(0)
    otherX(0)
    otherY(0)
  }

  // Пересборка: измерения зависят от раскладки, поэтому после ресайза и после загрузки шрифтов таймлайн строится заново.
  const rebuild = () => {
    tl.kill()
    const next = collect(root)
    if (!next) return
    Object.assign(refs, next)
    compact = refs.bars.length < root.querySelectorAll('[data-wave] > i').length
    gsap.set([...root.querySelectorAll('[data-wave] > i'), ...refs.words, refs.saidLayer, refs.otherLayer], { clearProps: 'all' })
    tl = build(root, refs, compact)
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

  root.addEventListener('pointerenter', onEnter)
  root.addEventListener('pointerleave', onLeave)
  root.addEventListener('pointermove', onMove)
  root.addEventListener('focusin', hold)
  root.addEventListener('focusout', release)
  refs.mic.addEventListener('click', replay)
  window.addEventListener('resize', onResize)

  return () => {
    disposed = true
    clearTimeout(resizeTimer)
    observer.disconnect()
    tl.kill()
    root.removeEventListener('pointerenter', onEnter)
    root.removeEventListener('pointerleave', onLeave)
    root.removeEventListener('pointermove', onMove)
    root.removeEventListener('focusin', hold)
    root.removeEventListener('focusout', release)
    refs.mic.removeEventListener('click', replay)
    window.removeEventListener('resize', onResize)
  }
}
