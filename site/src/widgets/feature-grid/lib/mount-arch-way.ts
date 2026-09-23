import { gsap, MOTION_SAFE_QUERY } from '@/shared/lib/motion'

/** Автопролистывание наборов, мс. */
const CYCLE = 6000
/** Шаг вычёркивания, с: список «гаснет» строка за строкой, пока справа собирается фраза. */
const STRIKE_STEP = 0.09

const all = <T extends Element>(root: Element, selector: string) => Array.from(root.querySelectorAll<T>(selector))
const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/**
 * Callback ref (React 19): «обычный Arch против одной фразы».
 * - Сцена при смене набора: шаги слева сыплются списком и вычёркиваются один за другим, справа поднимаются слова
 *   фразы, в конце выскакивает «1 sentence». Первый раз сцена играет, когда видна треть визуала; до этого шаги
 *   и фраза скрыты, чтобы не мелькнуть.
 * - Переключателей нет: раз в 6 с — следующий набор, только пока визуал виден, вкладка браузера открыта
 *   и курсор не над ним (дочитать шаги).
 * - Без motion-safe наборы переключаются мгновенно, шаги сразу вычеркнуты. SSR-разметка — законченная картинка.
 */
export function mountArchWay(root: HTMLElement | null): void | (() => void) {
  if (!root) return
  const panels = all<HTMLElement>(root, '[data-arch-panel]')
  if (!panels.length) return

  const motionSafe = window.matchMedia(MOTION_SAFE_QUERY)
  let current = 0
  let visible = false
  let held = false
  let played = false
  let tl: gsap.core.Timeline | undefined
  let timer: ReturnType<typeof setInterval> | undefined

  const parts = (panel: HTMLElement) => ({
    steps: all<HTMLElement>(panel, '[data-arch-step]'),
    texts: all<HTMLElement>(panel, '[data-arch-text]'),
    words: all<HTMLElement>(panel, '[data-arch-word]'),
    one: panel.querySelector<HTMLElement>('[data-arch-one]'),
  })

  const play = (panel: HTMLElement) => {
    tl?.kill()
    if (!motionSafe.matches) return
    const { steps, texts, words, one } = parts(panel)
    const strikeAt = 0.7
    tl = gsap.timeline({ defaults: { ease: 'expo.out' } })
    tl.fromTo(steps, { autoAlpha: 0, x: -8 }, { autoAlpha: 1, x: 0, duration: 0.3, stagger: 0.045, clearProps: 'all' }, 0)
      .fromTo(
        texts,
        { backgroundSize: '0% 1px', color: token('--color-ink-soft') },
        {
          backgroundSize: '100% 1px',
          color: token('--color-ink-dim'),
          duration: 0.35,
          stagger: STRIKE_STEP,
          ease: 'power3.out',
          clearProps: 'backgroundSize,color',
        },
        strikeAt,
      )
      .fromTo(words, { autoAlpha: 0, y: 14 }, { autoAlpha: 1, y: 0, duration: 0.6, stagger: 0.11, clearProps: 'all' }, 0.5)
    if (one) {
      tl.fromTo(
        one,
        { autoAlpha: 0, scale: 0.6 },
        { autoAlpha: 1, scale: 1, duration: 0.5, ease: 'back.out(2.2)', clearProps: 'all' },
        strikeAt + texts.length * STRIKE_STEP,
      )
    }
  }

  const next = () => {
    current = (current + 1) % panels.length
    panels.forEach((panel, k) => (panel.hidden = k !== current))
    play(panels[current]!)
  }

  const hold = () => (held = true)
  const release = () => (held = false)

  // До первого показа шаги и фраза скрыты, чтобы сцена не мигнула готовой картинкой.
  if (motionSafe.matches && root.getBoundingClientRect().top > window.innerHeight) {
    const { steps, words, one } = parts(panels[0]!)
    gsap.set([...steps, ...words, ...(one ? [one] : [])], { autoAlpha: 0 })
  }
  const observer = new IntersectionObserver(
    ([entry]) => {
      visible = !!entry?.isIntersecting
      if (visible && !played) {
        played = true
        play(panels[current]!)
        timer = setInterval(() => {
          if (visible && !held && !document.hidden) next()
        }, CYCLE)
      }
    },
    { threshold: 0.35 },
  )
  observer.observe(root)
  root.addEventListener('pointerenter', hold)
  root.addEventListener('pointerleave', release)

  return () => {
    clearInterval(timer)
    tl?.kill()
    observer.disconnect()
    root.removeEventListener('pointerenter', hold)
    root.removeEventListener('pointerleave', release)
  }
}
