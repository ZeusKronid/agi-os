import { useEffect, useRef } from 'react'

import type { DocPage } from '@/entities/doc'

import { DocsTree } from './docs-tree'

interface DocsDrawerProps {
  open: boolean
  onClose: () => void
  current: DocPage
  activeSection: string | null
}

/** Мобильная навигация документации: панель слева поверх страницы, закрывается по Escape и клику по подложке. */
export function DocsDrawer({ open, onClose, current, activeSection }: DocsDrawerProps) {
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <div
      hidden={!open}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      className="fixed inset-0 z-50 bg-canvas/60 md:hidden"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Docs navigation"
        className="absolute inset-y-0 left-0 w-[min(320px,86%)] overflow-y-auto border-r border-line bg-surface px-[18px] py-5 motion-safe:animate-tile"
      >
        <div className="mb-4 flex items-center justify-between">
          <span className="font-mono text-xs tracking-[0.36em] text-ink-muted uppercase">Docs</span>
          <button ref={closeRef} type="button" onClick={onClose} className="font-serif text-base text-ink-soft">
            Close
          </button>
        </div>
        <DocsTree current={current} activeSection={activeSection} onNavigate={onClose} />
      </div>
    </div>
  )
}
