import type { ComponentProps } from 'react'

import { cn } from '@/shared/lib/cn'

/**
 * Микрофон-кружок: Raised → Accent с расходящимися кольцами, пока слушает (`data-on="true"`).
 * Размер и позицию задаёт `className`; иконка — половина кнопки. Декоративный: `tabIndex={-1}`.
 */
export function MicButton({ className, ...props }: Omit<ComponentProps<'button'>, 'children'>) {
  return (
    <button
      type="button"
      tabIndex={-1}
      data-mic=""
      data-on="false"
      className={cn(
        'relative grid place-items-center rounded-full bg-raised text-ink-soft transition-[background-color,color] duration-200',
        'before:absolute before:-inset-px before:rounded-full before:opacity-0 before:inset-ring before:inset-ring-accent',
        'after:absolute after:-inset-px after:rounded-full after:opacity-0 after:inset-ring after:inset-ring-accent after:[animation-delay:.8s]',
        'hover:text-ink active:scale-[.94] data-[on=true]:bg-accent data-[on=true]:text-on-accent data-[on=true]:before:animate-ping-ring data-[on=true]:after:animate-ping-ring',
        className,
      )}
      {...props}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="size-1/2">
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      </svg>
    </button>
  )
}
