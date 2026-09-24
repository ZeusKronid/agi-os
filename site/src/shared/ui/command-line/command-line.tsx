import { useEffect, useRef, useState } from 'react'

import { cn } from '@/shared/lib/cn'

const COPIED_MS = 1600

interface CommandLineProps {
  text: string
  className?: string
}

/**
 * Строка с адресом или командой и кнопкой «Copy». Плашка Elevated, точка Accent слева,
 * состояние «Copied» зелёным `--color-ok` (как статусы в демо). Если clipboard недоступен,
 * выделяем текст, чтобы его можно было скопировать вручную.
 */
export function CommandLine({ text, className }: CommandLineProps) {
  const [copied, setCopied] = useState(false)
  const codeRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!copied) return
    const timer = window.setTimeout(() => setCopied(false), COPIED_MS)
    return () => window.clearTimeout(timer)
  }, [copied])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      const node = codeRef.current
      if (!node) return
      const range = document.createRange()
      range.selectNodeContents(node)
      const selection = window.getSelection()
      selection?.removeAllRanges()
      selection?.addRange(range)
    }
  }

  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-[10px] bg-elevated px-3.5 py-3 font-mono text-[13.5px] text-ink inset-ring inset-ring-line',
        className,
      )}
    >
      <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-accent" />
      <code ref={codeRef} className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap">
        {text}
      </code>
      <button
        type="button"
        onClick={copy}
        aria-live="polite"
        data-copied={copied}
        className="rounded-md px-2 py-1.5 text-[11px] tracking-[0.12em] text-ink-muted uppercase transition-[color,scale] duration-150 ease-out-strong hover:text-ink active:scale-[0.96] data-[copied=true]:text-ok"
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  )
}
