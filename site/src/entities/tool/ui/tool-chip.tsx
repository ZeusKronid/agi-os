import { cn } from '@/shared/lib/cn'

import type { Tool } from '../model/tools'
import { ToolIcon } from './tool-icon'

interface ToolChipProps {
  tool: Tool
  /** Подсвечен: заливка Accent и текст On Accent. Остальное — Elevated без рамки, Ink Muted. Меняется и на клиенте через `data-said`. */
  said: boolean
  className?: string
}

/** Пилюля инструмента с иконкой, без рамки. Узел `data-chip` трансформирует GSAP, поэтому позиционирует его родитель. */
export function ToolChip({ tool, said, className }: ToolChipProps) {
  return (
    <span
      data-chip=""
      data-tool={tool.id}
      data-said={said}
      className={cn(
        'group/chip flex h-8 items-center gap-[7px] rounded-full bg-elevated pr-[13px] pl-2.5 text-sm whitespace-nowrap text-ink-muted transition-[background-color,color] duration-500 ease-theme will-change-[transform,opacity] max-sm:h-7 max-sm:pr-[11px] max-sm:pl-[9px] max-sm:text-[13px]',
        'hover:bg-raised hover:text-ink data-[said=true]:bg-accent data-[said=true]:text-on-accent',
        className,
      )}
    >
      <ToolIcon
        icon={tool.icon}
        className="size-[15px] text-ink-dim transition-colors duration-500 ease-theme group-hover/chip:text-accent group-data-[said=true]/chip:text-on-accent max-sm:size-[13px]"
      />
      {tool.label}
    </span>
  )
}
