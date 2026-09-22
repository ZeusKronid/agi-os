import { gsap, REDUCED_MOTION_QUERY } from '@/shared/lib/motion'

/** Имена сцен для легенды; порядок совпадает с `[data-scene]` в разметке. */
export const sameSystemScenes = ['Try', 'Move', 'Yours'] as const

/** Начало каждой сцены и длина цикла, секунды. */
const SCENE_AT = [0, 3.5, 6.5] as const
const LOOP_S = 10.8
/** Мобильная раскладка Tailwind (`max-sm`): линия переноса вертикальна. */
const COMPACT_QUERY = '(max-width: 639.98px)'

const all = <T extends Element>(root: Element, selector: string) => Array.from(root.querySelectorAll<T>(selector))

interface Refs {
  scenes: HTMLElement[]
  labelDot: HTMLElement
  labelText: HTMLElement
  legend: HTMLElement[]
  cursor: SVGElement
  chips: HTMLElement[]
  previewDesk: HTMLElement
  link: HTMLElement
  packets: HTMLElement[]
  rows: HTMLElement[]
  rowBars: HTMLElement[]
  rowStatuses: HTMLElement[]
  target: HTMLElement
  laptop: HTMLElement
  pill: HTMLElement
  tags: HTMLElement[]
  caption: HTMLElement
}

function collect(root: HTMLElement): Refs | null {
  const one = <T extends Element>(selector: string) => root.querySelector<T>(selector)
  const scenes = all<HTMLElement>(root, '[data-scene]')
  const labelDot = one<HTMLElement>('[data-label-dot]')
  const labelText = one<HTMLElement>('[data-label-text]')
  const cursor = one<SVGElement>('[data-cursor]')
  const previewDesk = one<HTMLElement>('[data-desk="preview"]')
  const link = one<HTMLElement>('[data-link]')
  const target = one<HTMLElement>('[data-screen="target"]')
  const laptop = one<HTMLElement>('[data-screen="computer"]')?.parentElement
  const pill = one<HTMLElement>('[data-pill]')
  const caption = one<HTMLElement>('[data-caption]')
  if (scenes.length !== 3 || !labelDot || !labelText || !cursor || !previewDesk || !link || !target || !laptop || !pill || !caption) {
    return null
  }
  return {
    scenes,
    labelDot,
    labelText,
    legend: all<HTMLElement>(root, '[data-go]'),
    cursor,
    chips: all<HTMLElement>(root, '[data-chip]'),
    previewDesk,
    link,
    packets: all<HTMLElement>(root, '[data-packet]'),
    rows: all<HTMLElement>(root, '[data-row]'),
    rowBars: all<HTMLElement>(root, '[data-row-bar]'),
    rowStatuses: all<HTMLElement>(root, '[data-row-status]'),
    target,
    laptop,
    pill,
    tags: all<HTMLElement>(root, '[data-tag]'),
    caption,
  }
}

/** Смена сцены как в демо hero: уход 150 мс, вход 400 мс. Reduced motion: только проявление, без сдвига. */
function cut(tl: gsap.core.Timeline, scenes: HTMLElement[], index: number, at: number, shift: number) {
  scenes.forEach((scene, i) => {
    if (i !== index) tl.to(scene, { autoAlpha: 0, y: -shift * 0.75, duration: 0.15, ease: 'power1.in' }, at)
  })
  tl.fromTo(
    scenes[index]!,
    { autoAlpha: 0, y: shift },
    { autoAlpha: 1, y: 0, duration: 0.4, ease: 'expo.out', immediateRender: false },
    at + 0.15,
  )
}

function build(refs: Refs, reduced: boolean, compact: boolean): gsap.core.Timeline {
  const { scenes, labelDot, labelText, legend, cursor, chips, previewDesk, link, packets, rows, rowBars, rowStatuses, target, laptop, pill, tags, caption } = refs
  const shift = reduced ? 0 : 8
  const glide = reduced ? 0.01 : 0.8

  const setLabel = (text: string, live: boolean) => {
    labelText.textContent = text
    labelDot.dataset.live = String(live)
  }
  const reset = () => {
    chips.forEach((chip) => (chip.dataset.on = 'false'))
    previewDesk.dataset.wall = 'plain'
    previewDesk.dataset.nvim = 'off'
    target.dataset.hit = 'false'
    rowStatuses.forEach((status) => (status.textContent = ''))
  }

  // Курсор едет к чипам: позиции измерены относительно сцены «try» (она скрыта через visibility, но в потоке).
  const sceneRect = scenes[0]!.getBoundingClientRect()
  const targets = chips.map((chip) => {
    const rect = chip.getBoundingClientRect()
    return { x: rect.left + rect.width * 0.62 - sceneRect.left, y: rect.top + rect.height * 0.55 - sceneRect.top }
  })
  const start = { x: sceneRect.width * 0.5, y: sceneRect.height * 0.32 }
  // Точки переноса бегут вдоль линии: по горизонтали на десктопе, вниз на мобильном.
  const axis = compact ? 'y' : 'x'
  const length = (compact ? link.offsetHeight : link.offsetWidth) - 4

  const tl = gsap.timeline({ repeat: -1, paused: true, defaults: { ease: 'expo.out' } })

  // Сброс в начале каждого цикла.
  tl.set(scenes, { autoAlpha: 0 })
  tl.set(cursor, { x: start.x, y: start.y, autoAlpha: 0, scale: 1 })
  tl.set(packets, { [axis]: 0, opacity: 0 })
  tl.set(rows, { autoAlpha: 0, y: 4 })
  tl.set(rowBars, { scaleX: 0 })
  tl.set(laptop, { scale: 1 })
  tl.set([pill, ...tags, caption], { autoAlpha: 0 })
  tl.call(reset)

  // 01 · Try: курсор нажимает «coral wallpaper», затем «neovim»; превью меняется.
  tl.call(() => setLabel('live preview', true), undefined, 0)
  cut(tl, scenes, 0, 0, shift)
  tl.to(cursor, { autoAlpha: 1, duration: 0.3 }, 0.5)
  tl.to(cursor, { x: targets[0]?.x, y: targets[0]?.y, duration: glide, ease: 'power2.inOut' }, 0.6)
  tl.to(cursor, { scale: 0.82, duration: 0.09, yoyo: true, repeat: 1, ease: 'power1.inOut' }, 1.5)
  tl.call(
    () => {
      chips[0]!.dataset.on = 'true'
      previewDesk.dataset.wall = 'accent'
    },
    undefined,
    1.58,
  )
  tl.to(cursor, { x: targets[1]?.x, y: targets[1]?.y, duration: glide * 0.85, ease: 'power2.inOut' }, 2.0)
  tl.to(cursor, { scale: 0.82, duration: 0.09, yoyo: true, repeat: 1, ease: 'power1.inOut' }, 2.75)
  tl.call(
    () => {
      chips[1]!.dataset.on = 'true'
      previewDesk.dataset.nvim = 'on'
    },
    undefined,
    2.83,
  )
  tl.to(cursor, { autoAlpha: 0, duration: 0.3 }, 3.2)

  // 02 · Move: точки бегут к ноутбуку, строки System · Apps · Settings · Files получают «Copied».
  tl.call(() => setLabel('moving', true), undefined, SCENE_AT[1])
  cut(tl, scenes, 1, SCENE_AT[1], shift)
  if (!reduced) {
    tl.to(
      packets,
      {
        keyframes: {
          '0%': { [axis]: 0, opacity: 0, scale: 0.7 },
          '12%': { opacity: 1, scale: 1 },
          '88%': { opacity: 1 },
          '100%': { [axis]: length, opacity: 0, scale: 0.7 },
        },
        duration: 0.9,
        repeat: 1,
        ease: 'none',
        stagger: 0.3,
      },
      SCENE_AT[1] + 0.25,
    )
  }
  rows.forEach((row, index) => {
    const at = SCENE_AT[1] + 0.45 + index * 0.42
    tl.to(row, { autoAlpha: 1, y: 0, duration: 0.35 }, at)
    tl.to(rowBars[index]!, { scaleX: 1, duration: 0.5, ease: 'power2.inOut' }, at + 0.05)
    tl.call(() => (rowStatuses[index]!.textContent = 'Copied'), undefined, at + 0.5)
  })
  tl.call(() => (target.dataset.hit = 'true'), undefined, SCENE_AT[1] + 2.5)

  // 03 · Yours: ноутбук с тем же столом, пилюля «Installed», теги «kept», подпись.
  tl.call(() => setLabel('on your computer', false), undefined, SCENE_AT[2])
  cut(tl, scenes, 2, SCENE_AT[2], shift)
  tl.fromTo(laptop, { scale: 0.96 }, { scale: 1, duration: 0.6, immediateRender: false }, SCENE_AT[2] + 0.15)
  tl.to(pill, { autoAlpha: 1, duration: 0.35 }, SCENE_AT[2] + 0.55)
  tl.fromTo(tags, { y: 4 }, { autoAlpha: 1, y: 0, duration: 0.35, stagger: 0.12, immediateRender: false }, SCENE_AT[2] + 0.75)
  tl.to(caption, { autoAlpha: 1, duration: 0.4 }, SCENE_AT[2] + 1.25)
  tl.to(scenes[2]!, { autoAlpha: 0, duration: 0.5, ease: 'power1.in' }, LOOP_S - 0.6)
  tl.to(scenes[2]!, { duration: 0.05 }, LOOP_S - 0.05)

  // Легенда: активная сцена и её линия прогресса.
  tl.eventCallback('onUpdate', () => {
    const time = tl.time()
    const index = time >= SCENE_AT[2] ? 2 : time >= SCENE_AT[1] ? 1 : 0
    const end = index === 2 ? tl.duration() : SCENE_AT[index + 1]!
    const progress = (time - SCENE_AT[index]!) / (end - SCENE_AT[index]!)
    legend.forEach((button, i) => {
      button.dataset.active = String(i === index)
      button.style.setProperty('--p', i === index ? progress.toFixed(3) : i < index ? '1' : '0')
    })
  })

  return tl
}

/**
 * Callback ref (React 19): ролик из трёх сцен для карточки «What you tried is what you get».
 * - Таймлайн GSAP с повтором; идёт только пока визуал виден, встаёт на паузу при фокусе внутри.
 * - Клик по карточке запускает ролик заново; клик по легенде переводит к сцене.
 * - Позиции чипов для курсора и длина линии переноса измеряются из раскладки, поэтому после ресайза
 *   и загрузки шрифтов таймлайн собирается заново.
 * - Reduced motion: склейки без сдвига, курсор перескакивает, точки переноса не бегут.
 * - SSR-разметка показывает третью сцену: без JavaScript карточка остаётся законченной картинкой.
 */
export function mountSameSystemVisual(root: HTMLElement | null): void | (() => void) {
  if (!root) return
  const refs = collect(root)
  if (!refs) return

  const reducedMotion = window.matchMedia(REDUCED_MOTION_QUERY)
  const compactMedia = window.matchMedia(COMPACT_QUERY)

  let visible = false
  let held = false
  let tl = build(refs, reducedMotion.matches, compactMedia.matches)

  const sync = () => {
    if (visible && !held) tl.play()
    else tl.pause()
  }
  const hold = () => {
    held = true
    sync()
  }
  const release = () => {
    held = root.contains(document.activeElement)
    sync()
  }
  const onClick = (event: MouseEvent) => {
    const go = (event.target as Element | null)?.closest<HTMLElement>('[data-go]')
    if (go) {
      const index = Number(go.dataset.go)
      tl.play(SCENE_AT[index] ?? 0)
      return
    }
    tl.restart()
  }

  // Пересборка: измерения зависят от раскладки, поэтому после ресайза и загрузки шрифтов таймлайн строится заново.
  const rebuild = () => {
    tl.kill()
    const next = collect(root)
    if (!next) return
    Object.assign(refs, next)
    gsap.set(
      [refs.cursor, ...refs.scenes, ...refs.packets, ...refs.rows, ...refs.rowBars, refs.laptop, refs.pill, ...refs.tags, refs.caption],
      { clearProps: 'all' },
    )
    tl = build(refs, reducedMotion.matches, compactMedia.matches)
    if (visible) tl.restart()
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

  root.addEventListener('click', onClick)
  root.addEventListener('focusin', hold)
  root.addEventListener('focusout', release)
  window.addEventListener('resize', onResize)

  return () => {
    disposed = true
    clearTimeout(resizeTimer)
    observer.disconnect()
    tl.kill()
    root.removeEventListener('click', onClick)
    root.removeEventListener('focusin', hold)
    root.removeEventListener('focusout', release)
    window.removeEventListener('resize', onResize)
  }
}
