import { MOTION_SAFE_QUERY } from '@/shared/lib/motion'

import { angleBetween, rayAngle, SCENE, SIGNAL_NODES, SIGNAL_ORDER } from '../model/agent-signal'

/** Шаг автообхода агентов. */
const STEP_MS = 3000
/** Пауза после ухода курсора, после тапа и после потери фокуса. */
const RESUME_AFTER_POINTER_MS = 1200
const RESUME_AFTER_TAP_MS = 4000
/** Лучи ближе этого угла к направлению на агента разгораются. */
const LIT_SPAN = 0.5

/**
 * Callback ref (React 19): оживляет сцену «Сигнал» в карточке «Bring your own agent».
 * - Связь с агентом есть всегда: SSR-разметка уже подключена к первому агенту в `SIGNAL_ORDER`.
 * - Раз в `STEP_MS` линия сама перетекает к следующему агенту (lerp в rAF), лучи в его сторону разгораются.
 * - Курсор притягивает связь к ближайшему узлу, тап выбирает узел; автообход при этом ждёт и возобновляется сам.
 * - Автообход идёт только пока сцена видна. При reduced motion линия переходит мгновенно, обход остаётся:
 *   это смена обводки и текста, а не перемещение.
 */
export function mountAgentSignal(root: HTMLElement | null): void | (() => void) {
  if (!root) return

  const scene = root.querySelector<HTMLElement>('[data-signal-scene]')
  const link = root.querySelector<SVGLineElement>('[data-signal-link]')
  const dot = root.querySelector<SVGCircleElement>('[data-signal-dot]')
  const name = root.querySelector<HTMLElement>('[data-signal-name]')
  const auth = root.querySelector<HTMLElement>('[data-signal-auth]')
  const status = root.querySelector<HTMLElement>('[data-signal-status]')
  const nodes = Array.from(root.querySelectorAll<HTMLElement>('[data-signal-node]'))
  const rays = Array.from(root.querySelectorAll<SVGLineElement>('[data-signal-rays] line'))
  if (!scene || !link || !dot || !name || !auth || !status || nodes.length === 0) return

  const motionSafe = window.matchMedia(MOTION_SAFE_QUERY)

  let active = ''
  let target: { x: number; y: number } = { x: SCENE.cx, y: SCENE.cy }
  let pos: { x: number; y: number } = { x: SCENE.cx, y: SCENE.cy }
  let frame = 0
  let timer: ReturnType<typeof setInterval> | undefined
  let resumeTimer: ReturnType<typeof setTimeout> | undefined
  let swapTimer: ReturnType<typeof setTimeout> | undefined
  let visible = false

  const draw = () => {
    link.setAttribute('x2', pos.x.toFixed(1))
    link.setAttribute('y2', pos.y.toFixed(1))
    dot.setAttribute('cx', pos.x.toFixed(1))
    dot.setAttribute('cy', pos.y.toFixed(1))
  }

  const step = () => {
    frame = 0
    pos = { x: pos.x + (target.x - pos.x) * 0.14, y: pos.y + (target.y - pos.y) * 0.14 }
    draw()
    if (Math.abs(target.x - pos.x) + Math.abs(target.y - pos.y) > 0.4) frame = requestAnimationFrame(step)
  }

  const activate = (id: string) => {
    if (id === active) return
    const node = SIGNAL_NODES.find((candidate) => candidate.id === id)
    if (!node) return
    active = id

    nodes.forEach((element) => {
      element.dataset.on = String(element.dataset.signalNode === id)
    })
    rays.forEach((ray, index) => {
      ray.style.opacity = angleBetween(rayAngle(index), node.angle) < LIT_SPAN ? '1' : ''
    })

    clearTimeout(swapTimer)
    status.dataset.swap = 'true'
    swapTimer = setTimeout(() => {
      name.textContent = node.agent.label
      auth.textContent = node.auth
      status.dataset.swap = 'false'
    }, 150)

    target = { x: node.x, y: node.y }
    if (motionSafe.matches) {
      if (!frame) frame = requestAnimationFrame(step)
    } else {
      pos = { ...target }
      draw()
    }
  }

  const next = () => {
    const index = SIGNAL_ORDER.indexOf(active as (typeof SIGNAL_ORDER)[number])
    activate(SIGNAL_ORDER[(index + 1) % SIGNAL_ORDER.length] ?? SIGNAL_ORDER[0]!)
  }

  const stop = () => {
    if (timer !== undefined) clearInterval(timer)
    timer = undefined
  }
  const start = () => {
    stop()
    clearTimeout(resumeTimer)
    resumeTimer = undefined
    if (visible) timer = setInterval(next, STEP_MS)
  }
  const pause = (resumeAfter?: number) => {
    stop()
    clearTimeout(resumeTimer)
    if (resumeAfter !== undefined) resumeTimer = setTimeout(start, resumeAfter)
  }

  const nearest = (event: PointerEvent) => {
    const rect = scene.getBoundingClientRect()
    if (rect.width === 0) return undefined
    const scale = SCENE.width / rect.width
    const x = (event.clientX - rect.left) * scale
    const y = (event.clientY - rect.top) * scale
    let best: (typeof SIGNAL_NODES)[number] | undefined
    let bestDistance = Number.POSITIVE_INFINITY
    for (const node of SIGNAL_NODES) {
      const distance = Math.hypot(node.x - x, node.y - y)
      if (distance < bestDistance) {
        bestDistance = distance
        best = node
      }
    }
    return best
  }

  const onPointerMove = (event: PointerEvent) => {
    if (event.pointerType === 'touch') return
    const node = nearest(event)
    if (!node) return
    pause()
    activate(node.id)
  }
  const onPointerLeave = () => pause(RESUME_AFTER_POINTER_MS)
  const onClick = (event: MouseEvent) => {
    const element = (event.target as Element | null)?.closest<HTMLElement>('[data-signal-node]')
    const id = element?.dataset.signalNode
    if (!id) return
    activate(id)
    pause(RESUME_AFTER_TAP_MS)
  }

  root.addEventListener('pointermove', onPointerMove)
  root.addEventListener('pointerleave', onPointerLeave)
  root.addEventListener('click', onClick)

  const observer = new IntersectionObserver(
    (entries) => {
      const entry = entries[entries.length - 1]
      if (!entry) return
      visible = entry.isIntersecting
      // Пока пользователь держит связь курсором или тапом, ждём его паузу, а не перезапускаем обход.
      if (visible && resumeTimer === undefined) start()
      if (!visible) pause()
    },
    { threshold: 0.35 },
  )
  observer.observe(root)

  // Первый кадр совпадает с SSR-разметкой: связь уже с первым агентом, без промежуточного состояния.
  const first = SIGNAL_NODES.find((node) => node.id === SIGNAL_ORDER[0])
  if (first) {
    pos = { x: first.x, y: first.y }
    target = { ...pos }
    draw()
    activate(first.id)
  }

  return () => {
    stop()
    clearTimeout(resumeTimer)
    clearTimeout(swapTimer)
    cancelAnimationFrame(frame)
    observer.disconnect()
    root.removeEventListener('pointermove', onPointerMove)
    root.removeEventListener('pointerleave', onPointerLeave)
    root.removeEventListener('click', onClick)
  }
}
