import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

/**
 * Регистрирует ScrollTrigger. Вызывается только из callback ref'ов, то есть
 * исключительно в браузере; повторная регистрация в GSAP идемпотентна.
 */
export function registerScrollTrigger(): void {
  gsap.registerPlugin(ScrollTrigger)
}

export { gsap, ScrollTrigger }
