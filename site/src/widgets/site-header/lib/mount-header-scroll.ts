/**
 * Callback ref (React 19): шапка прозрачна над hero и получает подложку после начала скролла.
 * Lenis скроллит window, поэтому обычное событие `scroll` срабатывает и с ним, и без него.
 */
export function mountHeaderScroll(node: HTMLElement | null): void | (() => void) {
  if (!node) return

  // Пишем только смену состояния: запись на каждом кадре скролла пачкала бы стили всей шапки.
  const update = () => {
    const scrolled = String(window.scrollY > 8)
    if (node.dataset.scrolled !== scrolled) node.dataset.scrolled = scrolled
  }
  update()
  window.addEventListener('scroll', update, { passive: true })

  return () => window.removeEventListener('scroll', update)
}
