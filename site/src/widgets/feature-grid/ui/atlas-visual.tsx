import { ToolChip, tools } from '@/entities/tool'
import { cn } from '@/shared/lib/cn'

import { mountAtlasVisual } from '../lib/mount-atlas-visual'
import { setups } from '../model/setups'

const first = setups[0]!
const lit = new Set<string>(first.ids)

const label = 'font-mono text-[10.5px] tracking-[0.16em] text-ink-muted uppercase'

/**
 * Визуал широкой карточки «Arch was never this easy»: атлас всего, что можно назвать вслух.
 * Чипы без рамок идут потоком ровными рядами и переносятся по ширине карточки. Каждые 3 с загорается другой набор (`model/setups`),
 * подпись в углу называет его. Ролик — в `mountAtlasVisual`.
 */
export function AtlasVisual() {
  return (
    <div ref={mountAtlasVisual} className="relative px-6 pt-11 pb-7 max-sm:px-3 max-sm:pt-9 max-sm:pb-4">
      <span className={cn(label, 'absolute top-3.5 left-[18px] flex items-center gap-2')}>
        <i className="size-1.5 animate-blink rounded-full bg-accent" />
        your setup
        <span className="text-ink-dim">·</span>
        <span data-setup-name="" className="text-accent normal-case tracking-[0.06em]">
          {first.name}
        </span>
      </span>
      <span className={cn(label, 'absolute top-3.5 right-[18px] max-sm:hidden')}>{tools.length}+ named · no list</span>

      <ul className="m-0 flex list-none flex-wrap justify-center gap-x-2.5 gap-y-4 p-0 max-sm:gap-x-1.5 max-sm:gap-y-2">
        {tools.map((tool) => (
          // <li> только позиционирует; GSAP трансформирует внутренний чип (правило Tailwind v4 + GSAP).
          <li key={tool.id} data-chip-slot="">
            <ToolChip tool={tool} said={lit.has(tool.id)} />
          </li>
        ))}
        <li data-chip-slot="">
          <span
            data-chip=""
            className="flex h-8 items-center px-3 font-serif text-[15px] whitespace-nowrap text-ink-dim italic will-change-[transform,opacity] max-sm:h-7 max-sm:text-[14px]"
          >
            …and anything you can name
          </span>
        </li>
      </ul>
    </div>
  )
}
