import { cn } from '@/shared/lib/cn'

import type { Tool } from '../model/tools'
import { ToolIcon } from './tool-icon'

interface ToolChipProps {
  tool: Tool
  /** Названо вслух: заливка Accent и текст On Accent. Остальное — Ink Muted с рамкой Line. */
  said: boolean
  className?: string
}

/** Пилюля инструмента с иконкой. Узел `data-chip` трансформирует GSAP, поэтому позиционирует его родитель. */
export function ToolChip({ tool, said, className }: ToolChipProps) {
  return (
    <span
      data-chip=""
      data-said={said}
      className={cn(
        'flex h-8 items-center gap-[7px] rounded-full pr-[13px] pl-2.5 text-sm whitespace-nowrap transition-[box-shadow,color] duration-200 will-change-[transform,opacity] max-sm:h-7 max-sm:pr-[11px] max-sm:pl-[9px] max-sm:text-[13px]',
        said
          ? 'bg-accent text-on-accent'
          : 'text-ink-muted inset-ring inset-ring-line hover:text-ink hover:inset-ring-accent [&:hover_svg]:text-accent',
        className,
      )}
    >
      <ToolIcon
        icon={tool.icon}
        className={cn('size-[15px] transition-colors duration-200 max-sm:size-[13px]', said ? 'text-on-accent' : 'text-ink-dim')}
      />
      {tool.label}
    </span>
  )
}
