import type { CSSProperties } from 'react'

import { spokenToolIds, ToolChip, tools } from '@/entities/tool'
import { cn } from '@/shared/lib/cn'

import { mountAtlasVisual } from '../lib/mount-atlas-visual'

const spoken = new Set<string>(spokenToolIds)

/** Вертикальный сдвиг чипов по кругу, px: ряд читается не как таблица, а как созвездие. Только на десктопе. */
const DRIFT = [-7, 4, -2, 8, 0, -5, 3, -8, 6, -3, 1, 7, -6, 2] as const

const label = 'font-mono text-[10.5px] tracking-[0.16em] text-ink-muted uppercase'

/**
 * Визуал широкой карточки «Arch was never this easy»: атлас всего, что можно назвать вслух.
 * Чипы идут потоком и переносятся по ширине карточки; сказанное в демо залито Accent, остальное — рамка Line.
 * Последний чип — пунктирный «anything you can name»: список не закрытый. Ролик (вылет из центра, дрейф, параллакс) — в `mountAtlasVisual`.
 */
export function AtlasVisual() {
  return (
    <div ref={mountAtlasVisual} className="relative px-6 pt-11 pb-7 max-sm:px-3 max-sm:pt-9 max-sm:pb-4">
      <span className={cn(label, 'absolute top-3.5 left-[18px] flex items-center gap-2')}>
        <i data-label-dot="" className="size-1.5 animate-blink rounded-full bg-accent" />
        your setup
      </span>
      <span className={cn(label, 'absolute top-3.5 right-[18px] max-sm:hidden')}>{tools.length}+ named · no list</span>

      <ul className="m-0 flex list-none flex-wrap justify-center gap-x-3 gap-y-[18px] p-0 max-sm:gap-x-1.5 max-sm:gap-y-2">
        {tools.map((tool, index) => (
          // Сдвиг живёт на <li>; GSAP трансформирует внутренний чип (правило Tailwind v4 + GSAP).
          <li
            key={tool.id}
            data-chip-slot=""
            style={{ '--drift': `${DRIFT[index % DRIFT.length]}px` } as CSSProperties}
            className="translate-y-(--drift) max-sm:translate-y-0"
          >
            <ToolChip tool={tool} said={spoken.has(tool.id)} />
          </li>
        ))}
        <li data-chip-slot="" className="translate-y-[3px] max-sm:translate-y-0">
          <span
            data-chip=""
            data-said="false"
            className="flex h-8 items-center rounded-full border border-dashed border-line-strong px-[13px] text-sm whitespace-nowrap text-ink-dim italic will-change-[transform,opacity] max-sm:h-7 max-sm:px-[11px] max-sm:text-[13px]"
          >
            …anything you can name
          </span>
        </li>
      </ul>
    </div>
  )
}
