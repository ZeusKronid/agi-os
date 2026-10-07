import { siteConfig } from '@/shared/config'

type EventData = Record<string, string | number | boolean>

declare global {
  interface Window {
    umami?: { track: (event: string, data?: EventData) => void }
  }
}

/**
 * Скрипт Umami для `head()` корневого маршрута. Просмотры страниц (и переходы роутера), реферер и UTM
 * Umami собирает сам; `data-domains` выключает сбор на localhost и превью.
 */
export function analyticsScript() {
  const { scriptUrl, websiteId } = siteConfig.analytics
  return {
    src: scriptUrl,
    defer: true,
    'data-website-id': websiteId,
    'data-domains': new URL(siteConfig.url).hostname,
  }
}

/** Событие в Umami. Без скрипта (блокировщик, SSR, dev) — молча ничего. */
export function track(event: string, data?: EventData) {
  try {
    window.umami?.track(event, data)
  } catch {
    // Аналитика не должна ломать интерфейс.
  }
}

/**
 * Клики по внешним ссылкам (GitHub, релиз, пожертвования) одним делегированным слушателем,
 * без правки каждой ссылки. Возвращает отписку.
 */
export function mountOutboundTracking(): () => void {
  const onClick = (event: MouseEvent) => {
    const link = (event.target as Element | null)?.closest?.('a[href]')
    if (!(link instanceof HTMLAnchorElement) || link.host === window.location.host) return
    const label = (link.getAttribute('aria-label') ?? link.textContent ?? '').replace(/\s+/g, ' ').trim()
    track('outbound', { url: `${link.host}${link.pathname}`, label: label.slice(0, 60) })
  }
  document.addEventListener('click', onClick, true)
  return () => document.removeEventListener('click', onClick, true)
}

/** `section_view` один раз за визит страницы, когда верх секции поднялся выше 60% высоты экрана (работает и для высоких секций). */
export function trackSectionViews(ids: readonly string[]): () => void {
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        track('section_view', { section: entry.target.id })
        observer.unobserve(entry.target)
      }
    },
    { rootMargin: '0px 0px -40% 0px' },
  )
  for (const id of ids) {
    const node = document.getElementById(id)
    if (node) observer.observe(node)
  }
  return () => observer.disconnect()
}
