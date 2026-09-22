import { useNavigate } from '@tanstack/react-router'
import { useEffect, useId, useRef, useState, type ComponentProps, type KeyboardEvent as ReactKeyboardEvent } from 'react'

import { docIndexPage } from '@/entities/doc'
import { cn } from '@/shared/lib/cn'

import { searchDocs, type SearchHit } from '../model/search-index'

function SearchIcon(props: ComponentProps<'svg'>) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true" {...props}>
      <circle cx="7" cy="7" r="4.5" />
      <path d="M10.5 10.5L14 14" />
    </svg>
  )
}

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="inline-grid h-5 min-w-5 place-items-center rounded-[5px] bg-raised px-1.5 font-mono text-[11px] text-ink-soft inset-ring inset-ring-line-strong">
      {children}
    </kbd>
  )
}

interface DocsSearchButtonProps extends Omit<ComponentProps<'button'>, 'type'> {
  /** Без подсказки ⌘K — для мобильной панели. */
  compact?: boolean
}

/** Кнопка-«поле» открытия поиска. Сама палитра — `DocsSearchPalette`, состояние хранит страница. */
export function DocsSearchButton({ compact = false, className, ...props }: DocsSearchButtonProps) {
  return (
    <button
      type="button"
      className={cn(
        'flex h-10 w-full items-center gap-2.5 rounded-lg bg-surface px-3 text-[14px] text-ink-muted inset-ring inset-ring-line transition-[box-shadow] duration-200 hover:inset-ring-line-accent',
        compact && 'h-[38px]',
        className,
      )}
      {...props}
    >
      <SearchIcon className="size-[15px]" />
      <span>{compact ? 'Search' : 'Search docs'}</span>
      {!compact && (
        <span className="ml-auto">
          <Kbd>⌘K</Kbd>
        </span>
      )}
    </button>
  )
}

interface DocsSearchPaletteProps {
  open: boolean
  onOpen: () => void
  onClose: () => void
}

/**
 * Палитра поиска по секциям документации. ⌘K / Ctrl+K открывает, Esc закрывает,
 * ↑↓ двигают выбор, Enter переходит к секции. Пустой результат — отдельное состояние с подсказками.
 */
export function DocsSearchPalette({ open, onOpen, onClose }: DocsSearchPaletteProps) {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const listId = useId()
  const [query, setQuery] = useState('')
  const [hot, setHot] = useState(0)
  const hits = searchDocs(query)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        if (open) onClose()
        else onOpen()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onOpen, onClose])

  useEffect(() => {
    if (!open) return
    setQuery('')
    setHot(0)
    const timer = window.setTimeout(() => inputRef.current?.focus(), 30)
    return () => window.clearTimeout(timer)
  }, [open])

  const go = (hit: SearchHit) => {
    onClose()
    const hash = hit.section.id
    if (hit.page.slug === docIndexPage.slug) void navigate({ to: '/docs', hash })
    else void navigate({ to: '/docs/$slug', params: { slug: hit.page.slug }, hash })
  }

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (hits.length === 0) return
      setHot((prev) => (prev + (event.key === 'ArrowDown' ? 1 : hits.length - 1)) % hits.length)
    } else if (event.key === 'Enter') {
      const hit = hits[hot]
      if (hit) go(hit)
    } else if (event.key === 'Escape') {
      onClose()
    }
  }

  return (
    <div
      hidden={!open}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
      className="fixed inset-0 z-50 bg-canvas/70 px-4 pt-20 pb-4 backdrop-blur-sm"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search docs"
        className="mx-auto max-w-[560px] origin-top overflow-hidden rounded-[14px] bg-surface inset-ring inset-ring-line-strong motion-safe:animate-tile"
      >
        <input
          ref={inputRef}
          id="docs-search-input"
          type="search"
          role="combobox"
          aria-expanded={hits.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          autoComplete="off"
          placeholder="Search docs… try “preview” or “luks”"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setHot(0)
          }}
          onKeyDown={onKeyDown}
          className="h-[54px] w-full border-b border-line bg-transparent px-[18px] text-base text-ink outline-none placeholder:text-ink-dim [&::-webkit-search-cancel-button]:appearance-none"
        />
        <div id={listId} role="listbox" className="grid max-h-[340px] gap-0.5 overflow-y-auto p-2">
          {hits.length === 0 ? (
            <p className="px-4 py-7 text-center text-[14.5px] text-ink-muted">
              <span className="mb-1 block font-serif text-xl text-ink">Nothing for “{query.trim()}”</span>
              Try “preview”, “luks”, “ollama” or “dual boot”.
            </p>
          ) : (
            hits.map((hit, index) => (
              <button
                key={`${hit.page.slug}#${hit.section.id}`}
                type="button"
                role="option"
                aria-selected={index === hot}
                onMouseEnter={() => setHot(index)}
                onClick={() => go(hit)}
                className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors duration-150 aria-selected:bg-elevated"
              >
                <span aria-hidden="true" className="size-[5px] rounded-full bg-accent" />
                <span className="font-serif text-[17px] text-ink">{hit.section.title}</span>
                <span className="font-mono text-[10.5px] tracking-[0.16em] text-ink-dim uppercase">{hit.page.short}</span>
              </button>
            ))
          )}
        </div>
        <div className="flex gap-3.5 border-t border-line px-4 py-2.5 font-mono text-[10.5px] tracking-[0.08em] text-ink-dim">
          <span className="inline-flex items-center gap-1.5">
            <Kbd>↑↓</Kbd> move
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Kbd>↵</Kbd> open
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Kbd>esc</Kbd> close
          </span>
        </div>
      </div>
    </div>
  )
}
