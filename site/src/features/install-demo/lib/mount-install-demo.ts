import { gsap, REDUCED_MOTION_QUERY, speechProfile } from '@/shared/lib/motion'

/** Старт каждого шага (с) и длина ролика; между повторами пауза. Preview длиннее: в конце курсор нажимает кнопку. */
const MARKS = [0, 4.6, 10.2, 14.6] as const
const TOTAL = 19.2
const REPEAT_DELAY = 1.2
/** Индексы подписей состояния: у шага Build две — «building» и «moving» после галочки. */
const STATE_BY_STEP = [0, 1, 2, 4] as const
const STATE_MOVING = 3

const all = <T extends Element>(root: Element, selector: string) => Array.from(root.querySelectorAll<T>(selector))

interface Refs {
  tabs: HTMLElement[]
  scenes: HTMLElement[]
  rim: SVGRectElement
  statusDot: HTMLElement
  states: HTMLElement[]
  mic: HTMLElement
  bars: HTMLElement[]
  words: HTMLElement[]
  lines: HTMLElement[]
  tiles: HTMLElement[]
  files: HTMLElement[]
  editorLines: HTMLElement[]
  cta: HTMLElement
  cursor: SVGElement
  ring: SVGElement
  progress: SVGElement
  ticks: SVGElement[]
  check: SVGElement
  checkPath: SVGElement
  ready: HTMLElement
  reads: HTMLElement[]
  readChecks: SVGElement[]
  installRing: SVGElement
  installCheck: SVGElement
  installTitle: HTMLElement
  installRows: HTMLElement[]
}

function collect(root: HTMLElement): Refs | null {
  const one = <T extends Element>(selector: string) => root.querySelector<T>(selector)
  const tabs = all<HTMLElement>(root, '[data-demo-step]')
  const scenes = all<HTMLElement>(root, '[data-demo-scene]')
  const rim = one<SVGRectElement>('[data-rim-path]')
  const statusDot = one<HTMLElement>('[data-status-dot]')
  const mic = one<HTMLElement>('[data-mic]')
  const cta = one<HTMLElement>('[data-cta]')
  const cursor = one<SVGElement>('[data-cursor]')
  const ring = one<SVGElement>('[data-ring]')
  const progress = one<SVGElement>('[data-progress]')
  const check = one<SVGElement>('[data-check]')
  const checkPath = check?.querySelector<SVGElement>('path')
  const ready = one<HTMLElement>('[data-ready]')
  const installRing = one<SVGElement>('[data-install-ring]')
  const installCheck = one<SVGElement>('[data-install-check]')
  const installTitle = one<HTMLElement>('[data-install-title]')
  if (
    tabs.length !== MARKS.length ||
    scenes.length !== MARKS.length ||
    !rim || !statusDot || !mic || !cta || !cursor || !ring || !progress || !check || !checkPath || !ready || !installRing || !installCheck || !installTitle
  ) {
    return null
  }
  return {
    tabs,
    scenes,
    rim,
    statusDot,
    states: all<HTMLElement>(root, '[data-state]'),
    mic,
    // На мобильном каждый второй столбик скрыт CSS — анимируем только видимые.
    bars: all<HTMLElement>(root, '[data-wave] > i').filter((bar) => bar.offsetWidth > 0),
    words: all<HTMLElement>(root, '[data-word]'),
    lines: all<HTMLElement>(root, '[data-line]'),
    tiles: all<HTMLElement>(root, '[data-tile]'),
    files: all<HTMLElement>(root, '[data-file]'),
    editorLines: all<HTMLElement>(root, '[data-editor-line]'),
    cta,
    cursor,
    ring,
    progress,
    ticks: all<SVGElement>(root, '[data-tick]'),
    check,
    checkPath,
    ready,
    reads: all<HTMLElement>(root, '[data-read]'),
    readChecks: all<SVGElement>(root, '[data-read-check]'),
    installRing,
    installCheck,
    installTitle,
    installRows: all<HTMLElement>(root, '[data-install-row]'),
  }
}

type Timeline = gsap.core.Timeline

/** Смена значения `data-*` как шаг таймлайна: перемотка назад честно возвращает прежнее значение. */
const attr = (tl: Timeline, targets: Element | Element[], name: string, value: string, at: number) =>
  tl.set(targets, { attr: { [name]: value } }, at)

/** Смена сцены как раньше: уход 150 мс, вход 400 мс. */
function cut(tl: Timeline, scenes: HTMLElement[], index: number, at: number, reduced: boolean) {
  scenes.forEach((scene, i) => {
    if (i !== index) tl.to(scene, { autoAlpha: 0, y: reduced ? 0 : -6, duration: 0.15, ease: 'power1.in' }, at)
  })
  tl.fromTo(scenes[index]!, { autoAlpha: 0, y: reduced ? 0 : 8 }, { autoAlpha: 1, y: 0, duration: 0.4 }, at + 0.15)
}

function showState(tl: Timeline, states: HTMLElement[], index: number, at: number) {
  states.forEach((state, i) => tl.to(state, { autoAlpha: i === index ? 1 : 0, duration: 0.25 }, at))
}

/** Рамка-прогресс: штрих дорисовывается линейно внутри каждого шага, чтобы совпадать с легендой. */
function rim(tl: Timeline, rect: SVGRectElement) {
  tl.set(rect, { strokeDashoffset: 1 }, 0)
  MARKS.forEach((mark, i) => {
    const end = MARKS[i + 1] ?? TOTAL
    tl.to(rect, { strokeDashoffset: 1 - end / TOTAL, duration: end - mark, ease: 'none' }, mark)
  })
}

/** 01 · Listening: волна слева направо, кластеры краснеют, фраза набирается по словам; затем волна схлопывается. */
function listen(tl: Timeline, refs: Refs, at: number, reduced: boolean) {
  const { bars, words, mic } = refs
  const N = bars.length
  const { amplitude, clusters, heardAt } = speechProfile(N)
  const waveRect = bars[0]?.parentElement?.getBoundingClientRect()
  const collapseX = bars.map((bar) => {
    if (!waveRect) return 0
    const rect = bar.getBoundingClientRect()
    return waveRect.left + waveRect.width / 2 - (rect.left + rect.width / 2)
  })

  tl.set(bars, { scaleY: 0.04, opacity: 1, x: 0 }, at)
  tl.set(words, { opacity: 0, y: 6 }, at)
  attr(tl, bars, 'data-hit', 'false', at)
  attr(tl, words, 'data-hit', 'false', at)
  attr(tl, mic, 'data-on', 'true', at + 0.05)
  bars.forEach((bar, i) => tl.to(bar, { scaleY: amplitude[i], duration: 0.4, ease: 'power3.out' }, at + 0.4 + (i / N) * 3.2))
  clusters.forEach((cluster, k) => attr(tl, cluster.map((i) => bars[i]!), 'data-hit', 'true', at + heardAt[k]!))
  let spoken = 0
  words.forEach((word) => {
    const isTool = !!word.dataset.tool
    const when = at + (isTool ? (heardAt[spoken++] ?? 0) : (heardAt[2] ?? 0) + 0.3)
    tl.to(word, { opacity: 1, y: 0, duration: 0.45 }, when)
    if (isTool) attr(tl, word, 'data-hit', 'true', when + 0.08)
  })
  attr(tl, mic, 'data-on', 'false', at + 3.9)
  tl.to(words, { opacity: 0, duration: 0.35, ease: 'power1.in' }, at + 4.05)
  if (reduced) {
    tl.to(bars, { opacity: 0, duration: 0.35 }, at + 4.05)
    return
  }
  bars.forEach((bar, i) =>
    tl.to(bar, { x: collapseX[i], scaleY: 0.04, opacity: 0, duration: 0.55, ease: 'power3.in' }, at + 4.0 + Math.abs(i / N - 0.5) * 0.15),
  )
}

/**
 * 02 · Preview: терминал печатает строки, плитка файлов подсвечивается, фокус переходит по окнам.
 * В конце снизу по центру появляется кнопка «Get this setup», курсор подъезжает из правого нижнего угла и нажимает.
 */
function preview(tl: Timeline, refs: Refs, at: number, reduced: boolean) {
  const { lines, tiles, files, editorLines, cta, cursor } = refs
  tl.set(lines, { opacity: 0, x: reduced ? 0 : -4 }, at)
  tl.set(editorLines, { scaleX: 0 }, at)
  tl.set(cta, { opacity: 0, y: reduced ? 0 : 8, scale: 1 }, at)
  tl.set(cursor, { opacity: 0, x: reduced ? 0 : 150, y: reduced ? 0 : 110, scale: 1 }, at)
  attr(tl, files, 'data-hot', 'false', at)
  attr(tl, tiles, 'data-focus', 'false', at)
  if (tiles[0]) attr(tl, tiles[0], 'data-focus', 'true', at)
  lines.forEach((line, i) => tl.to(line, { opacity: 1, x: 0, duration: 0.35 }, at + 0.35 + i * 0.55))
  if (files[1]) attr(tl, files[1], 'data-hot', 'true', at + 1.3)
  tl.to(editorLines, { scaleX: 1, duration: 0.5, stagger: 0.08 }, at + 1.7)
  ;[2.5, 3.3].forEach((offset, k) => {
    const tile = tiles[k + 1]
    if (!tile || tile.offsetWidth === 0) return
    attr(tl, tiles, 'data-focus', 'false', at + offset)
    attr(tl, tile, 'data-focus', 'true', at + offset)
  })
  tl.to(cta, { opacity: 1, y: 0, duration: 0.45 }, at + 3.4)
  tl.to(cursor, { opacity: 1, duration: 0.25 }, at + 3.6)
  tl.to(cursor, { x: 0, y: 0, duration: 0.8, ease: 'power2.inOut' }, at + 3.6)
  // Нажатие: кнопка и курсор чуть сжимаются и возвращаются (150 мс, как у настоящей кнопки).
  tl.to(cta, { scale: 0.96, duration: 0.12, ease: 'power2.out', yoyo: true, repeat: 1 }, at + 4.55)
  tl.to(cursor, { scale: 0.88, duration: 0.12, ease: 'power2.out', yoyo: true, repeat: 1 }, at + 4.55)
}

/** 03 · Build: кольцо вращается и дорисовывается, слова загораются; на галочке — строка «moving» и галочки у слов. */
function build(tl: Timeline, refs: Refs, at: number, reduced: boolean) {
  const { ring, progress, ticks, check, checkPath, ready, reads, readChecks } = refs
  tl.set(ring, { rotation: -90, scale: 1, opacity: 1, transformOrigin: '50% 50%' }, at)
  tl.set(progress, { strokeDashoffset: 201 }, at)
  tl.set(ticks, { opacity: 1 }, at)
  tl.set(check, { opacity: 1, scale: 1 }, at)
  tl.set(checkPath, { strokeDashoffset: 34 }, at)
  tl.set(ready, { opacity: 0, y: reduced ? 0 : 8 }, at)
  tl.set(reads, { opacity: 0, scale: reduced ? 1 : 0.9, transformOrigin: '50% 50%' }, at)
  tl.set(readChecks, { opacity: 0, scale: 0.6 }, at)
  if (!reduced) tl.to(ring, { rotation: 270, duration: 2.6, ease: 'none' }, at + 0.15)
  tl.to(progress, { strokeDashoffset: 0, duration: 2.4, ease: 'power2.inOut' }, at + 0.25)
  reads.forEach((read, i) => tl.to(read, { opacity: 1, scale: 1, duration: 0.4 }, at + 0.45 + i * 0.4))
  tl.to(ticks, { opacity: 0, duration: 0.25, stagger: { each: 0.006, from: 'random' } }, at + 2.65)
  if (!reduced) tl.fromTo(ring, { scale: 1 }, { scale: 1.06, duration: 0.18, ease: 'power2.out', yoyo: true, repeat: 1 }, at + 2.7)
  tl.to(checkPath, { strokeDashoffset: 0, duration: 0.4, ease: 'power2.out' }, at + 2.8)
  tl.to(ready, { opacity: 1, y: 0, duration: 0.5 }, at + 3.0)
  tl.to(readChecks, { opacity: 1, scale: 1, duration: 0.35, stagger: 0.09 }, at + 3.0)
}

/** 04 · Install: кольцо замыкается, галочка, строки статуса. */
function install(tl: Timeline, refs: Refs, at: number, reduced: boolean) {
  const { installRing, installCheck, installTitle, installRows } = refs
  tl.set(installRing, { strokeDashoffset: 201 }, at)
  tl.set(installCheck, { opacity: 0, scale: 0.8 }, at)
  tl.set(installTitle, { opacity: 0, y: reduced ? 0 : 6 }, at)
  tl.set(installRows, { opacity: 0, y: reduced ? 0 : 5 }, at)
  tl.to(installTitle, { opacity: 1, y: 0, duration: 0.5 }, at + 0.1)
  tl.to(installRing, { strokeDashoffset: 0, duration: 1.8, ease: 'power2.inOut' }, at + 0.2)
  tl.to(installCheck, { opacity: 1, scale: 1, duration: 0.35 }, at + 2.0)
  installRows.forEach((row, i) => tl.to(row, { opacity: 1, y: 0, duration: 0.45 }, at + 0.8 + i * 0.55))
}

/** Штрих рамки: размеры прямоугольника ставятся в пикселях, `pathLength=1` делает dash-математику независимой от размера. */
function sizeRim(rect: SVGRectElement) {
  const box = rect.ownerSVGElement?.getBoundingClientRect()
  if (!box) return
  rect.setAttribute('width', String(Math.max(0, box.width - 1.5)))
  rect.setAttribute('height', String(Math.max(0, box.height - 1.5)))
}

function buildTimeline(refs: Refs, reduced: boolean): Timeline {
  const { scenes, states, statusDot } = refs
  // force3D: false — иначе 84 столбика волны на время твина становятся отдельными слоями композитора.
  const tl = gsap.timeline({ repeat: -1, repeatDelay: REPEAT_DELAY, paused: true, defaults: { ease: 'expo.out', force3D: false } })

  tl.set(scenes, { autoAlpha: 0 }, 0)
  tl.set(scenes[0]!, { autoAlpha: 1, y: 0 }, 0)
  showState(tl, states, STATE_BY_STEP[0], 0)
  attr(tl, statusDot, 'data-live', 'true', 0)
  listen(tl, refs, MARKS[0] + 0.15, reduced)

  cut(tl, scenes, 1, MARKS[1], reduced)
  showState(tl, states, STATE_BY_STEP[1], MARKS[1])
  preview(tl, refs, MARKS[1] + 0.15, reduced)

  cut(tl, scenes, 2, MARKS[2], reduced)
  showState(tl, states, STATE_BY_STEP[2], MARKS[2])
  build(tl, refs, MARKS[2] + 0.15, reduced)
  showState(tl, states, STATE_MOVING, MARKS[2] + 3.15)

  cut(tl, scenes, 3, MARKS[3], reduced)
  showState(tl, states, STATE_BY_STEP[3], MARKS[3])
  attr(tl, statusDot, 'data-live', 'false', MARKS[3] + 2.2)
  install(tl, refs, MARKS[3] + 0.15, reduced)

  tl.to(scenes[3]!, { autoAlpha: 0, duration: 0.4, ease: 'power1.in' }, TOTAL - 0.4)
  rim(tl, refs.rim)
  tl.to({}, { duration: 0.01 }, TOTAL)
  return tl
}

/**
 * Callback ref (React 19): ролик из четырёх сцен в окне установщика.
 * - Один GSAP-таймлайн с повтором; состояние сцен — только твины и `attr`, без callback'ов,
 *   поэтому клик по шагу (перемотка) честно откатывает или доигрывает всё до нужного момента.
 * - Идёт, пока демо видно; пауза при наведении и фокусе внутри (у пользователя всегда есть способ остановить).
 * - Легенда: клик и ← → по шагам; `data-active/done`, `aria-selected` и `inert` сцен обновляются по позиции таймлайна.
 * - Клик по микрофону запускает ролик заново. Рамка-штрих измеряется в пикселях, поэтому после ресайза
 *   рамка и точки схлопывания волны пересчитываются заново.
 * - Reduced motion: сцены и слова только проявляются, кольцо не вращается; автопрокрутка остаётся, как у остальных демо.
 * - SSR-разметка показывает первую сцену с невидимой фразой: без JavaScript окно остаётся законченной картинкой.
 */
export function mountInstallDemo(root: HTMLElement | null): void | (() => void) {
  if (!root) return
  const refs = collect(root)
  if (!refs) return

  const reducedMotion = window.matchMedia(REDUCED_MOTION_QUERY)
  let visible = false
  let held = false
  let step = -1
  let tl = gsap.timeline({ paused: true })

  const running = () => visible && !held
  const sync = () => {
    if (running()) tl.play()
    else tl.pause()
  }

  const setStep = (index: number) => {
    if (index === step) return
    step = index
    refs.tabs.forEach((tab, i) => {
      tab.dataset.active = String(i === index)
      tab.dataset.done = String(i < index)
      tab.setAttribute('aria-selected', String(i === index))
    })
    refs.scenes.forEach((scene, i) => {
      scene.inert = i !== index
    })
  }
  const stepAt = (time: number) => MARKS.reduce<number>((found, mark, i) => (time >= mark ? i : found), 0)

  const rebuild = () => {
    const time = tl.time()
    tl.kill()
    gsap.set(
      [...refs.scenes, ...refs.states, ...refs.bars, ...refs.words, ...refs.lines, ...refs.editorLines, refs.cta, refs.cursor, refs.ring, refs.ready, ...refs.reads],
      { clearProps: 'transform,opacity,visibility' },
    )
    const next = collect(root)
    if (next) Object.assign(refs, next)
    sizeRim(refs.rim)
    tl = buildTimeline(refs, reducedMotion.matches)
    tl.eventCallback('onUpdate', () => setStep(stepAt(tl.time())))
    tl.time(Math.min(time, TOTAL))
    sync()
  }

  const goto = (index: number) => {
    const target = MARKS[((index % MARKS.length) + MARKS.length) % MARKS.length]!
    tl.seek(target)
    setStep(stepAt(target))
  }

  const hold = () => {
    held = true
    sync()
  }
  const release = () => {
    held = root.matches(':hover') || root.contains(document.activeElement)
    sync()
  }
  const replay = () => tl.restart()
  const onTabClick = refs.tabs.map((tab, index) => {
    const handler = () => goto(index)
    tab.addEventListener('click', handler)
    return handler
  })
  const onTabKey = (event: KeyboardEvent) => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    const next = (step + (event.key === 'ArrowRight' ? 1 : -1) + MARKS.length) % MARKS.length
    goto(next)
    refs.tabs[next]?.focus()
  }

  let resizeTimer: ReturnType<typeof setTimeout> | undefined
  const onResize = () => {
    clearTimeout(resizeTimer)
    resizeTimer = setTimeout(rebuild, 250)
  }

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

  rebuild()
  observer.observe(root)
  root.addEventListener('pointerenter', hold)
  root.addEventListener('pointerleave', release)
  root.addEventListener('focusin', hold)
  root.addEventListener('focusout', release)
  root.addEventListener('keydown', onTabKey)
  refs.mic.addEventListener('click', replay)
  reducedMotion.addEventListener('change', rebuild)
  window.addEventListener('resize', onResize)

  return () => {
    clearTimeout(resizeTimer)
    observer.disconnect()
    tl.kill()
    refs.tabs.forEach((tab, index) => {
      const handler = onTabClick[index]
      if (handler) tab.removeEventListener('click', handler)
    })
    root.removeEventListener('pointerenter', hold)
    root.removeEventListener('pointerleave', release)
    root.removeEventListener('focusin', hold)
    root.removeEventListener('focusout', release)
    root.removeEventListener('keydown', onTabKey)
    refs.mic.removeEventListener('click', replay)
    reducedMotion.removeEventListener('change', rebuild)
    window.removeEventListener('resize', onResize)
  }
}
