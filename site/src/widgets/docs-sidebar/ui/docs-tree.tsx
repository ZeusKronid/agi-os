import { useState } from 'react'

import { docChapters, docPagesOf, DocLink, type DocChapterId, type DocPage } from '@/entities/doc'
import { cn } from '@/shared/lib/cn'
import { ChevronDownIcon } from '@/shared/ui/icon'

interface DocsTreeProps {
  current: DocPage
  /** Активная секция текущей страницы — подсвечивается в подпунктах (scroll-spy). */
  activeSection: string | null
  onNavigate?: () => void
}

/**
 * Дерево разделов. Getting Started и раздел текущей страницы раскрыты по умолчанию.
 * Под текущей страницей показаны её секции, активная подсвечена коралловой линией слева.
 */
export function DocsTree({ current, activeSection, onNavigate }: DocsTreeProps) {
  const [open, setOpen] = useState<ReadonlySet<DocChapterId>>(() => new Set(['start', current.chapter]))

  const toggle = (id: DocChapterId) => {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <nav aria-label="Docs" className="grid gap-1">
      {docChapters.map((chapter) => {
        const isOpen = open.has(chapter.id)
        const listId = `docs-tree-${chapter.id}`
        return (
          <div key={chapter.id}>
            <button
              type="button"
              aria-expanded={isOpen}
              aria-controls={listId}
              onClick={() => toggle(chapter.id)}
              className={cn(
                'flex w-full items-center justify-between rounded-md px-2 py-2 font-serif text-[17px] text-ink-soft transition-colors duration-200 hover:text-ink',
                isOpen && 'text-ink',
              )}
            >
              {chapter.label}
              <ChevronDownIcon
                data-open={isOpen}
                className="size-3 text-ink-dim transition-[rotate,color] duration-250 ease-out-strong data-[open=true]:rotate-180 data-[open=true]:text-accent"
              />
            </button>
            <ul id={listId} hidden={!isOpen} className="mt-0.5 mb-2 ml-3 grid border-l border-line pl-2">
              {docPagesOf(chapter.id).map((page) => {
                const isCurrent = page.slug === current.slug
                return (
                  <li key={page.slug}>
                    <DocLink
                      page={page}
                      aria-current={isCurrent ? 'page' : undefined}
                      onClick={onNavigate}
                      className={cn(
                        '-ml-[9px] block border-l border-transparent py-1.5 pl-3 text-[14px] text-ink-muted transition-colors duration-200 hover:text-ink',
                        isCurrent && 'border-accent text-ink',
                      )}
                    >
                      {page.short}
                    </DocLink>
                    {isCurrent && page.sections.length > 1 && (
                      <ul className="grid">
                        {page.sections.map((section) => (
                          <li key={section.id}>
                            <a
                              href={`#${section.id}`}
                              aria-current={activeSection === section.id ? 'true' : undefined}
                              onClick={onNavigate}
                              className={cn(
                                '-ml-[9px] block border-l border-transparent py-1.5 pl-6 text-[13.5px] text-ink-muted transition-colors duration-200 hover:text-ink',
                                activeSection === section.id && 'border-accent text-ink',
                              )}
                            >
                              {section.title}
                            </a>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )
      })}
    </nav>
  )
}
