import { spokenSentence, spokenToolIds, ToolIcon, tools, type Tool } from '@/entities/tool'
import { cn } from '@/shared/lib/cn'
import { CheckIcon } from '@/shared/ui/icon'
import { ProgressRing } from '@/shared/ui/progress-ring'
import { MicButton, SpokenSentence, Wave } from '@/shared/ui/voice'

import { mountWordsVisual } from '../lib/mount-words-visual'

const WAVE_BARS = 84

/** Позиции чипов в «созвездии», % от визуала. Только для десктопа; на мобильном чипы идут потоком. */
const CONSTELLATION: Record<string, readonly [number, number]> = {
  btrfs: [32, 16],
  'no-desktop': [56, 16],
  steam: [88, 16],
  hyprland: [18, 40],
  'dark-theme': [41, 40],
  neovim: [64, 40],
  zsh: [85, 40],
  kde: [16, 66],
  sway: [34, 66],
  docker: [53, 66],
  python: [74, 66],
  xfce: [93, 66],
  waybar: [26, 89],
  tiling: [47, 89],
}

const spoken = new Set<string>(spokenToolIds)
const spokenTools = spokenToolIds.map((id) => tools.find((tool) => tool.id === id)).filter((tool): tool is Tool => !!tool)
const otherTools = tools.filter((tool) => !spoken.has(tool.id))

const label = 'font-mono text-[10.5px] tracking-[0.16em] text-ink-muted uppercase'

function Chip({ tool, said }: { tool: Tool; said: boolean }) {
  const position = CONSTELLATION[tool.id] ?? [50, 50]
  return (
    // Позиционирует внешний <li>; GSAP трансформирует внутренний <span> (правило Tailwind v4 + GSAP).
    <li
      style={{ left: `${position[0]}%`, top: `${position[1]}%` }}
      className="pointer-events-auto absolute -translate-x-1/2 -translate-y-1/2 max-sm:static max-sm:translate-none"
    >
      <span
        data-chip=""
        data-said={said}
        className={cn(
          'flex h-8 items-center gap-[7px] rounded-full pr-[13px] pl-2.5 text-sm whitespace-nowrap transition-[box-shadow,color] duration-200 will-change-[transform,opacity] max-sm:h-7 max-sm:pr-[11px] max-sm:pl-[9px] max-sm:text-[13px]',
          said
            ? 'bg-accent text-on-accent'
            : 'text-ink-muted inset-ring inset-ring-line hover:text-ink hover:inset-ring-accent [&:hover_svg]:text-accent',
        )}
      >
        <ToolIcon
          icon={tool.icon}
          className={cn('size-[15px] transition-colors duration-200 max-sm:size-[13px]', said ? 'text-on-accent' : 'text-ink-dim')}
        />
        {tool.label}
      </span>
    </li>
  )
}

/**
 * Визуал карточки «Say it in words»: три сцены подряд, как короткое видео.
 * 01 слушает (волна, фраза по словам) → 02 думает (кольцо, слова, галочка «installed») → 03 набор (чипы вылетают из кольца).
 * SSR-разметка показывает третью сцену; таймлайн живёт в `mountWordsVisual`.
 */
export function WordsVisual() {
  return (
    <div ref={mountWordsVisual} className="absolute inset-0">
      <span data-label="" className={cn(label, 'absolute top-3.5 left-[18px] z-10 flex items-center gap-2')}>
        <i data-label-dot="" className="size-1.5 animate-blink rounded-full bg-accent data-[live=false]:hidden" data-live="false" />
        <span data-label-text="">your setup</span>
      </span>

      {/* 01 · Listening */}
      <div data-scene="" className="invisible absolute inset-0 opacity-0 will-change-[transform,opacity]">
        <MicButton className="absolute top-1/2 left-4 z-10 size-7 -translate-y-1/2 max-sm:top-3 max-sm:right-3 max-sm:left-auto max-sm:translate-y-0" />
        <Wave
          bars={WAVE_BARS}
          className="absolute top-[44%] right-[18px] left-[58px] h-16 -translate-y-1/2 max-sm:top-[40%] max-sm:right-3 max-sm:left-3"
        />
        <SpokenSentence
          words={spokenSentence}
          className="absolute inset-x-6 bottom-[22px] text-xl leading-[1.3] tracking-[-0.012em] max-sm:inset-x-3 max-sm:bottom-4 max-sm:text-[17px]"
        />
      </div>

      {/* 02 · Thinking → installed */}
      <div data-scene="" className="invisible absolute inset-0 grid place-content-center justify-items-center gap-3.5 opacity-0 will-change-[transform,opacity]">
        <ProgressRing className="size-[76px]" />
        <ul className="m-0 flex list-none gap-[18px] p-0 font-mono text-[11.5px] tracking-[0.04em] text-ink-soft max-sm:flex-wrap max-sm:justify-center max-sm:gap-x-3.5 max-sm:gap-y-2 max-sm:px-3">
          {spokenTools.map((tool) => (
            <li key={tool.id} data-read="" className="flex items-center gap-1.5 opacity-0">
              <i className="size-[5px] rounded-full bg-accent" />
              {tool.label.toLowerCase()}
              <CheckIcon data-read-check="" className="size-[11px] text-accent opacity-0 [transform:scale(.6)]" />
            </li>
          ))}
        </ul>
        <span data-done="" className={cn(label, 'absolute inset-x-0 bottom-3.5 text-center opacity-0')}>
          {spokenTools.length} of {spokenTools.length} · installed
        </span>
      </div>

      {/* 03 · Your setup — без JavaScript видна сразу */}
      <div data-scene="" className="absolute inset-0 will-change-[transform,opacity] max-sm:flex max-sm:flex-wrap max-sm:content-center max-sm:justify-center max-sm:gap-1.5 max-sm:px-3 max-sm:pt-9 max-sm:pb-3">
        <ul data-layer="said" className="pointer-events-none absolute inset-0 m-0 list-none p-0 will-change-transform max-sm:contents">
          {spokenTools.map((tool) => (
            <Chip key={tool.id} tool={tool} said />
          ))}
        </ul>
        <ul data-layer="other" className="pointer-events-none absolute inset-0 m-0 list-none p-0 will-change-transform max-sm:contents">
          {otherTools.map((tool) => (
            <Chip key={tool.id} tool={tool} said={false} />
          ))}
        </ul>
      </div>
    </div>
  )
}
