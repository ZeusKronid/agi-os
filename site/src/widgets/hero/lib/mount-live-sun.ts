import { gsap, MOTION_SAFE_QUERY } from '@/shared/lib/motion'

/** Насколько вытягивается луч в центре линзы и её ширина (радианы). */
const LENS_REACH = 0.62
const LENS_SIGMA = 0.3
/** В покое линза медленно качается вокруг зенита. */
const IDLE_STRENGTH = 0.45
const IDLE_SWING = 0.55
const IDLE_PERIOD_MS = 2600
/** Насколько голос удлиняет луч и сколько энергии волны за кадр считается «громко». */
const VOICE_REACH = 0.7
const VOICE_FULL = 0.22
/** Длительность входа солнца (CSS: задержки лучей + 1,2 с роста); после неё начинается дыхание. */
const ENTRANCE_MS = 2300
/** Сколько ждать свободного главного потока до старта входа. */
const IDLE_TIMEOUT_MS = 1200
/** Шаги демо (Listen · Preview · Build · Install) — внутренние точки дуги: 205°, 243°, 297°, 335°. */
const STEP_DOTS = [1, 2, 3, 4] as const

interface LiveRay {
  el: SVGLineElement
  angle: number
  inner: number
  length: number
  opacity: number
  /** Доля голоса у луча: у каждого своя, чтобы поле шелестело, а не пульсировало целиком. */
  voice: number
}

const num = (el: Element, name: string) => Number(el.getAttribute(name))
const clamp = (value: number) => Math.min(1, Math.max(0, value))
/** Детерминированный шум 0..1 по индексу луча. */
const noise = (index: number) => {
  const x = Math.sin(index * 12.9898) * 43758.5453
  return x - Math.floor(x)
}

/**
 * Callback ref (React 19) на секцию hero: оживляет `Sunburst variant="live"`.
 * - Подъём из-за заголовка и дорисовка дуги — CSS, но старт даёт этот модуль: SVG-анимации идут в главном
 *   потоке, и если начать их с первой отрисовки, гидрация и запуск остальных анимаций страницы (длинные
 *   задачи на 60–100 мс) замораживают солнце посреди подъёма. Поэтому `data-sun-go` ставится, когда
 *   главный поток свободен (`requestIdleCallback`), а до этого на месте солнца пусто.
 * - Лучи тянутся к курсору (линза), в покое линза медленно качается. Ниже горизонта курсор отражается вверх,
 *   так что линза идёт за ним по горизонтали. Тап работает так же.
 * - Солнце слушает демо: пока микрофон включён, энергия волны (сумма изменений столбиков за кадр)
 *   удлиняет лучи. Активный шаг демо подсвечивает свою точку на дуге, пройденные остаются крупными.
 * - Цикл идёт, только пока hero виден и вкладка открыта. SSR-разметка — законченный статичный восход.
 */
export function mountLiveSun(root: HTMLElement | null): void | (() => void) {
  if (!root) return
  const svg = root.querySelector<SVGSVGElement>('svg[data-sun-live]')
  if (!svg) return

  const cx = Number(svg.dataset.cx)
  const cy = Number(svg.dataset.cy)
  const rays: LiveRay[] = Array.from(svg.querySelectorAll<SVGLineElement>('[data-sun-ray]'), (el, index) => {
    const x1 = num(el, 'x1') - cx
    const y1 = num(el, 'y1') - cy
    const inner = Math.hypot(x1, y1)
    const angle = Math.atan2(y1, x1)
    return {
      el,
      angle: angle <= 0 ? angle + 2 * Math.PI : angle,
      inner,
      length: Math.hypot(num(el, 'x2') - cx, num(el, 'y2') - cy) - inner,
      opacity: num(el, 'stroke-opacity'),
      voice: 0.4 + noise(index) * 0.9,
    }
  })
  const dots = Array.from(svg.querySelectorAll<SVGCircleElement>('[data-sun-dot]'))
  const tabs = Array.from(root.querySelectorAll<HTMLElement>('[data-demo-step]'))
  const mic = root.querySelector<HTMLElement>('[data-mic]')
  const bars = Array.from(root.querySelectorAll<HTMLElement>('[data-wave] > i'))
  const previous = new Float32Array(bars.length)

  const motionSafe = window.matchMedia(MOTION_SAFE_QUERY)
  const lens = { angle: 1.5 * Math.PI, strength: 0 }
  const target = { angle: 1.5 * Math.PI, strength: 0 }
  let start = Number.POSITIVE_INFINITY
  let pointer = false
  let voice = 0
  let visible = false
  let frame = 0

  const listen = () => {
    let energy = 0
    bars.forEach((bar, index) => {
      const scale = Number(gsap.getProperty(bar, 'scaleY')) || 0
      energy += Math.abs(scale - (previous[index] ?? 0))
      previous[index] = scale
    })
    return mic?.dataset.on === 'true' ? clamp(energy / VOICE_FULL) : 0
  }

  const paint = (now: number) => {
    // Пока звучит голос, линза уступает ему.
    const strength = lens.strength * (1 - voice * 0.6)
    for (const ray of rays) {
      const delta = ray.angle - lens.angle
      const lit = Math.exp(-(delta * delta) / (LENS_SIGMA * LENS_SIGMA)) * strength
      const heard = voice * ray.voice * (0.65 + 0.35 * Math.sin(now * 0.011 + ray.angle * 9))
      const outer = ray.inner + ray.length * (1 + LENS_REACH * lit) * (1 + VOICE_REACH * heard)
      ray.el.setAttribute('x2', (cx + outer * Math.cos(ray.angle)).toFixed(1))
      ray.el.setAttribute('y2', (cy + outer * Math.sin(ray.angle)).toFixed(1))
      ray.el.setAttribute('stroke-opacity', Math.min(1, ray.opacity + 0.4 * lit + 0.35 * heard).toFixed(2))
    }

    const step = tabs.findIndex((tab) => tab.dataset.active === 'true')
    STEP_DOTS.forEach((dotIndex, stepIndex) => {
      const dot = dots[dotIndex]
      if (!dot || step < 0) return
      const pulse = motionSafe.matches ? 0.9 * (0.5 + 0.5 * Math.sin(now * 0.008)) : 0
      const radius = stepIndex < step ? 2.6 : stepIndex === step ? 2.8 + pulse : 1.6
      dot.setAttribute('r', radius.toFixed(2))
      dot.setAttribute('opacity', stepIndex <= step ? '1' : '0.55')
    })
  }

  const tick = (now: number) => {
    frame = 0
    const smooth = motionSafe.matches
    if (!pointer) {
      // Дыхание начинается после входа, чтобы не спорить с ростом лучей.
      const breathing = smooth && now > start
      target.angle = 1.5 * Math.PI + (breathing ? IDLE_SWING * Math.sin((now - start) / IDLE_PERIOD_MS) : 0)
      target.strength = breathing ? IDLE_STRENGTH : 0
    }
    const ease = smooth ? 0.12 : 1
    lens.angle += (target.angle - lens.angle) * ease
    lens.strength += (target.strength - lens.strength) * ease
    // Голос: быстрая атака, медленный спад, как у индикатора уровня.
    const heard = smooth ? listen() : 0
    voice += (heard - voice) * (heard > voice ? 0.35 : 0.08)
    paint(now)
    if (visible && !document.hidden) frame = requestAnimationFrame(tick)
  }
  const wake = () => {
    if (!frame && visible && !document.hidden) frame = requestAnimationFrame(tick)
  }

  const aim = (event: PointerEvent) => {
    const box = svg.getBoundingClientRect()
    const view = svg.viewBox.baseVal
    const scale = view.width / box.width
    const x = view.x + (event.clientX - box.left) * scale
    const y = view.y + (event.clientY - box.top) * scale
    let angle = Math.atan2(y - cy, x - cx)
    if (angle < 0) angle += 2 * Math.PI
    // Ниже горизонта отражаем курсор вверх: линза идёт за ним по горизонтали.
    if (angle < Math.PI) angle = 2 * Math.PI - angle
    pointer = true
    target.angle = angle
    target.strength = 1
    wake()
  }
  const release = () => {
    pointer = false
    wake()
  }

  const go = () => {
    svg.setAttribute('data-sun-go', '')
    start = performance.now() + ENTRANCE_MS
  }
  // В Safari нет `requestIdleCallback` — там просто короткая пауза.
  const hasIdle = typeof window.requestIdleCallback === 'function'
  const idle = hasIdle ? window.requestIdleCallback(go, { timeout: IDLE_TIMEOUT_MS }) : window.setTimeout(go, 300)

  const observer = new IntersectionObserver(([entry]) => {
    visible = !!entry?.isIntersecting
    wake()
  })
  observer.observe(root)
  root.addEventListener('pointermove', aim)
  root.addEventListener('pointerdown', aim)
  root.addEventListener('pointerleave', release)
  document.addEventListener('visibilitychange', wake)

  return () => {
    if (hasIdle) window.cancelIdleCallback(idle)
    else window.clearTimeout(idle)
    cancelAnimationFrame(frame)
    observer.disconnect()
    root.removeEventListener('pointermove', aim)
    root.removeEventListener('pointerdown', aim)
    root.removeEventListener('pointerleave', release)
    document.removeEventListener('visibilitychange', wake)
  }
}
