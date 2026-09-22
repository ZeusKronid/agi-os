import { gsap, REDUCED_MOTION_QUERY } from '@/shared/lib/motion'

import { liveRequests, type LiveEffect, type LiveWindow } from '../model/live-requests'

/** Пауза перед первым словом, шаг между словами, пауза между последним словом и изменением стола, показ результата. */
const LEAD_MS = 250
const WORD_MS = 200
const APPLY_MS = 450
const HOLD_MS = 2600
/** Задержка продолжения после ухода курсора и после возвращения во вьюпорт. */
const RESUME_MS = 800

const all = <T extends Element>(root: Element, selector: string) => Array.from(root.querySelectorAll<T>(selector))

/**
 * Callback ref (React 19): оживляет визуал «Try it live first».
 * - Пять запросов по кругу: слова фразы проявляются как распознанная речь, затем стол меняется.
 *   Состояние стола — `data-*` на рамке, смена вида целиком описана в CSS.
 * - Идёт, пока визуал виден. Наведение честно ставит цикл на паузу на текущем результате
 *   (окна в это время фокусируются под курсором), уход курсора продолжает со следующего запроса.
 * - Клик по строке запроса сразу переводит к следующему запросу.
 * - Reduced motion: слова появляются разом, «bouncy» не подпрыгивает; переходы цвета остаются.
 * - SSR-разметка показывает результат последнего запроса, поэтому без JavaScript карточка законченна.
 */
export function mountLiveVisual(root: HTMLElement | null): void | (() => void) {
  if (!root) return

  const frame = root.querySelector<HTMLElement>('[data-frame]')
  const say = root.querySelector<HTMLElement>('[data-say]')
  const count = root.querySelector<HTMLElement>('[data-count]')
  const phrases = all<HTMLElement>(root, '[data-phrase]')
  const windows = all<HTMLElement>(root, '[data-window]')
  if (!frame || !say || !count || phrases.length !== liveRequests.length || windows.length === 0) return

  const reducedMotion = window.matchMedia(REDUCED_MOTION_QUERY)

  let step = 0
  let visible = false
  let held = false
  let phase: 'idle' | 'speaking' | 'hold' = 'idle'
  const timers = new Set<ReturnType<typeof setTimeout>>()

  const later = (fn: () => void, ms: number) => {
    const id = setTimeout(() => {
      timers.delete(id)
      fn()
    }, ms)
    timers.add(id)
  }
  const clear = () => {
    timers.forEach(clearTimeout)
    timers.clear()
  }

  const focus = (id: LiveWindow) => {
    windows.forEach((win) => {
      win.dataset.focus = String(win.dataset.window === id)
    })
  }

  const bounce = () => {
    if (reducedMotion.matches) return
    gsap.fromTo(
      windows,
      { scale: 0.86, opacity: 0.4 },
      { scale: 1, opacity: 1, duration: 0.65, ease: 'back.out(2.4)', stagger: 0.07, clearProps: 'transform,opacity' },
    )
  }

  const apply = (effect: LiveEffect) => {
    switch (effect) {
      case 'dark':
        frame.dataset.theme = 'dark'
        break
      case 'bar':
        frame.dataset.bar = 'off'
        focus('files')
        break
      case 'rice':
        frame.dataset.rice = 'true'
        focus('editor')
        break
      case 'bouncy':
        frame.dataset.bouncy = 'true'
        bounce()
        break
      case 'reset':
        frame.dataset.theme = 'light'
        frame.dataset.bar = 'on'
        frame.dataset.rice = 'false'
        frame.dataset.bouncy = 'false'
        focus('terminal')
        break
    }
  }

  const show = (index: number, wordsOn: boolean) => {
    phrases.forEach((phrase, i) => {
      phrase.hidden = i !== index
      all<HTMLElement>(phrase, '[data-word]').forEach((word) => {
        word.dataset.on = String(wordsOn)
      })
    })
    count.textContent = `${index + 1} / ${liveRequests.length}`
  }

  /** Дословно завершает текущий шаг: фраза целиком, результат применён. Нужна для паузы и ухода из вьюпорта. */
  const settle = () => {
    clear()
    say.dataset.rec = 'false'
    const request = liveRequests[step]
    // До первого запроса в покое показан результат последнего: его и оставляем.
    if (!request || phase === 'idle') return
    show(step, true)
    if (phase === 'speaking') apply(request.effect)
    phase = 'hold'
  }

  const next = () => {
    step = (step + 1) % liveRequests.length
    speak()
  }

  const speak = () => {
    if (!visible || held) return
    const request = liveRequests[step]
    const phrase = phrases[step]
    if (!request || !phrase) return
    clear()
    phase = 'speaking'
    show(step, false)
    say.dataset.rec = 'true'
    const words = all<HTMLElement>(phrase, '[data-word]')
    const per = reducedMotion.matches ? 0 : WORD_MS
    words.forEach((word, index) => {
      later(() => {
        word.dataset.on = 'true'
      }, LEAD_MS + index * per)
    })
    later(() => {
      say.dataset.rec = 'false'
      apply(request.effect)
      phase = 'hold'
      later(next, HOLD_MS)
    }, LEAD_MS + words.length * per + APPLY_MS)
  }

  const onSayClick = () => {
    const advance = phase !== 'speaking'
    settle()
    held = false
    if (advance) next()
    else speak()
  }
  const hold = () => {
    held = true
    settle()
  }
  const release = () => {
    held = false
    if (!visible) return
    clear()
    later(next, RESUME_MS)
  }

  const onWindowEnter = windows.map((win) => {
    const handler = () => focus(win.dataset.window as LiveWindow)
    win.addEventListener('pointerenter', handler)
    return handler
  })
  const onWindowClick = windows.map((win) => {
    const handler = () => {
      focus(win.dataset.window as LiveWindow)
      if (!reducedMotion.matches) gsap.fromTo(win, { scale: 0.97 }, { scale: 1, duration: 0.25, ease: 'power2.out', clearProps: 'transform' })
    }
    win.addEventListener('click', handler)
    return handler
  })

  say.addEventListener('click', onSayClick)
  root.addEventListener('pointerenter', hold)
  root.addEventListener('pointerleave', release)

  const observer = new IntersectionObserver(
    (entries) => {
      const entry = entries[entries.length - 1]
      if (!entry) return
      visible = entry.isIntersecting
      if (visible) {
        clear()
        later(phase === 'hold' ? next : speak, RESUME_MS)
      } else {
        settle()
      }
    },
    { threshold: 0.35 },
  )
  observer.observe(root)

  return () => {
    clear()
    observer.disconnect()
    gsap.killTweensOf(windows)
    say.removeEventListener('click', onSayClick)
    root.removeEventListener('pointerenter', hold)
    root.removeEventListener('pointerleave', release)
    windows.forEach((win, index) => {
      const enter = onWindowEnter[index]
      const click = onWindowClick[index]
      if (enter) win.removeEventListener('pointerenter', enter)
      if (click) win.removeEventListener('click', click)
    })
  }
}
