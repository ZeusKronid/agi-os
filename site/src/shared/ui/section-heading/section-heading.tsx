import type { ReactNode } from 'react'

import { cn } from '@/shared/lib/cn'
import { Reveal } from '@/shared/ui/reveal'
import { Sunburst } from '@/shared/ui/sunburst'

interface SectionHeadingProps {
  id: string
  label: string
  /** Заголовок; одно слово можно выделить через `<em>` — оно станет курсивным и коралловым. */
  title: ReactNode
  children?: ReactNode
  className?: string
}

/** Шапка секции: маленький восход, разреженный лейбл капсом, заголовок антиквой. Всегда по центру. */
export function SectionHeading({ id, label, title, children, className }: SectionHeadingProps) {
  return (
    <Reveal className={cn('mb-14 flex flex-col items-center gap-[18px] text-center', className)}>
      <Sunburst variant="mark" className="-mb-1 h-[61px] w-[150px] text-accent opacity-90" />
      <p className="font-mono text-xs tracking-[0.36em] text-ink-muted uppercase">{label}</p>
      <h2
        id={id}
        className="font-serif text-[clamp(36px,4.5vw,60px)] leading-[1.04] tracking-[-0.024em] text-balance [&_em]:text-accent"
      >
        {title}
      </h2>
      {children}
    </Reveal>
  )
}
