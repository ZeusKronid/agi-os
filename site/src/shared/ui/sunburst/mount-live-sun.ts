import { gsap, MOTION_SAFE_QUERY } from '@/shared/lib/motion'

/** Насколько вытягивается луч в центре линзы и её ширина (радианы). */
const LENS_REACH = 0.62
const LENS_SIGMA = 0.3
/** В покое линза медленно качается вокруг зенита. */
const IDLE_STRENGTH = 0.45
const IDLE_SWING = 0.55
const IDLE_PERIOD_MS = 2600
/**
 * Насколько голос демо удлиняет луч сверх постоянного сияния (CSS `sun-shimmer` уже даёт до +70%)
 * и сколько энергии волны за кадр считается «громко». Небольшая добавка: слова чуть раскачивают поле.
 */
const VOICE_REACH = 0.25
const VOICE_FULL = 0.22
/** Шаги демо (Listen · Preview · Build · Install) — внутренние точки дуги: 205°, 243°, 297°, 335°. */
const STEP_DOTS = [1, 2, 3, 4] as const

interface LiveRay {
  el: HTMLElement
  angle: number
  length: number
  opacity: number
  /** Длина и прозрачность из SSR-разметки: к ним луч возвращается в покое. */
  restWidth: string
  restOpacity: string
  /** Доля голоса у луча: у каждого своя, чтобы поле шелестело, а не пульсировало целиком. */
  voice: number
}

const clamp = (value: number) => Math.min(1, Math.max(0, value))
/** Детерминированный шум 0..1 по индексу луча. */
const noise = (index: number) => {
  const x = Math.sin(index * 12.9898) * 43758.5453
  return x - Math.floor(x)
}

/**
 * Callback ref (React 19) на секцию с `Sunburst variant="live"` (hero, футер): оживляет лучи.
 * Демо (`[data-demo-step]`, `[data-mic]`, `[data-wave]`) необязательно: без него солнце просто дышит и тянется к курсору.
 * - Подъём из-за заголовка, рост лучей и дорисовка дуги — композиторный CSS с первой отрисовки
 *   (`Sunburst variant="live"`); здесь только длина лучей-полосок и точки. Дыхание включается сразу,
 *   поверх роста лучей; если линза и голос в нуле (reduced motion), лучи не трогаются.
 * - Лучи тянутся к курсору (линза), в покое линза медленно качается. Ниже горизонта курсор отражается вверх,
 *   так что линза идёт за ним по горизонтали. Тап работает так же.
 * - Солнце слушает демо: пока микрофон включён, энергия волны (сумма изменений столбиков за кадр)
 *   удлиняет лучи. Активный шаг демо подсвечивает свою точку на дуге, пройденные остаются крупными.
 * - Цикл идёт, только пока hero виден и вкладка открыта. SSR-разметка — законченный статичный восход.
 */
export function mountLiveSun(root: HTMLElement | null): void | (() => void) {
  if (!root) return
  const sun = root.querySelector<HTMLElement>('[data-sun-live]')
  if (!sun) return

  // Центр солнца — на нижнем крае обёртки (горизонт), по горизонтали — доля ширины.
  const center = Number(sun.dataset.center)
  const units = Number(sun.dataset.units)
  const rays: LiveRay[] = Array.from(sun.querySelectorAll<HTMLElement>('[data-sun-ray]'), (el, index) => {
    const angle = Number(el.dataset.angle)
    return {
      el,
      angle: angle <= 0 ? angle + 2 * Math.PI : angle,
      length: Number(el.dataset.length),
      opacity: Number(el.dataset.opacity),
      restWidth: el.style.width,
      restOpacity: el.style.opacity,
      voice: 0.4 + noise(index) * 0.9,
    }
  })
  const dots = Array.from(root.querySelectorAll<SVGCircleElement>('[data-sun-dot]'))
  const tabs = Array.from(root.querySelectorAll<HTMLElement>('[data-demo-step]'))
  const mic = root.querySelector<HTMLElement>('[data-mic]')
  const bars = Array.from(root.querySelectorAll<HTMLElement>('[data-wave] > i'))
  const previous = new Float32Array(bars.length)

  const motionSafe = window.matchMedia(MOTION_SAFE_QUERY)
  const lens = { angle: 1.5 * Math.PI, strength: 0 }
  const target = { angle: 1.5 * Math.PI, strength: 0 }
  // Дыхание начинается сразу, поверх роста лучей, как в прототипе: без паузы после входа.
  const start = performance.now()
  let raysAtRest = true
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

  const paintRays = (now: number) => {
    // Пока звучит голос, линза уступает ему.
    const strength = lens.strength * (1 - voice * 0.6)
    // Лучи в покое уже совпадают с SSR-разметкой: не трогаем их, пока что-то не сдвинется.
    const rest = strength < 0.002 && voice < 0.002
    if (rest && raysAtRest) return
    raysAtRest = rest
    if (rest) {
      for (const ray of rays) {
        ray.el.style.width = ray.restWidth
        ray.el.style.opacity = ray.restOpacity
      }
      return
    }
    for (const ray of rays) {
      const delta = ray.angle - lens.angle
      const lit = Math.exp(-(delta * delta) / (LENS_SIGMA * LENS_SIGMA)) * strength
      const heard = voice * ray.voice * (0.65 + 0.35 * Math.sin(now * 0.011 + ray.angle * 9))
      const length = ray.length * (1 + LENS_REACH * lit) * (1 + VOICE_REACH * heard)
      ray.el.style.width = `calc(${length.toFixed(2)} * 100cqw / ${units})`
      ray.el.style.opacity = Math.min(1, ray.opacity + 0.4 * lit + 0.35 * heard).toFixed(2)
    }
  }

  const paint = (now: number) => {
    paintRays(now)

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
      const breathing = smooth
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
    const box = sun.getBoundingClientRect()
    let angle = Math.atan2(event.clientY - box.bottom, event.clientX - (box.left + box.width * center))
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
    cancelAnimationFrame(frame)
    observer.disconnect()
    root.removeEventListener('pointermove', aim)
    root.removeEventListener('pointerdown', aim)
    root.removeEventListener('pointerleave', release)
    document.removeEventListener('visibilitychange', wake)
  }
}
