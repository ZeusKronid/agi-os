import { useEffect, useState } from 'react'

const DEFAULT_ROOT_MARGIN = '-112px 0px -70% 0px'

/**
 * Какой из заголовков сейчас «читается»: последний, чья верхняя кромка прошла зону под шапкой.
 * Lenis скроллит window, поэтому IntersectionObserver с корнем по умолчанию работает и с ним, и без него.
 */
export function useActiveSection(ids: readonly string[], rootMargin = DEFAULT_ROOT_MARGIN): string | null {
  const [active, setActive] = useState<string | null>(ids[0] ?? null)

  useEffect(() => {
    setActive(ids[0] ?? null)
    const nodes = ids.map((id) => document.getElementById(id)).filter((node): node is HTMLElement => node !== null)
    if (nodes.length === 0) return

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(entry.target.id)
        }
      },
      { rootMargin, threshold: 0 },
    )
    nodes.forEach((node) => observer.observe(node))

    return () => observer.disconnect()
  }, [ids, rootMargin])

  return active
}
