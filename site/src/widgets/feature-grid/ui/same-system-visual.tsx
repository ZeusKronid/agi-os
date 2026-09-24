import type { ReactNode } from 'react'

import { cn } from '@/shared/lib/cn'
import { CheckIcon } from '@/shared/ui/icon'

import { mountSameSystemVisual, sameSystemScenes } from '../lib/mount-same-system-visual'

/** Правки, которые курсор «делает» в превью; те же слова, что и в чипах соседних карточек. */
const CHANGES = ['coral wallpaper', 'neovim'] as const
/** Что переезжает во второй сцене. */
const COPY_ROWS = ['System', 'Apps', 'Settings', 'Files'] as const
const PACKETS = 3

const label = 'font-mono text-[10.5px] tracking-[0.16em] text-ink-muted uppercase'
const scene = 'absolute inset-x-[18px] top-10 bottom-4 will-change-[transform,opacity] max-sm:inset-x-3.5 max-sm:bottom-3'
/** Раскладка сцен try и yours: подписи по сторонам, окно на всю высоту; на мобильном окно сверху, подписи под ним. */
const sides = 'grid grid-cols-[150px_1fr_150px] items-center gap-4 max-sm:grid-cols-1 max-sm:grid-rows-[1fr_auto_auto] max-sm:gap-2.5'
const sideLeft = 'grid justify-items-end gap-1.5 self-center max-sm:order-2 max-sm:grid-flow-col max-sm:justify-center max-sm:justify-items-center'
const sideRight =
  'max-w-[15ch] self-center font-serif text-[15px] leading-[1.3] text-ink-muted italic max-sm:order-3 max-sm:max-w-none max-sm:text-center max-sm:text-[14px]'
const center = 'grid h-full min-h-0 max-sm:order-1'

interface DeskProps {
  id: string
  wall: 'plain' | 'accent'
  nvim: 'on' | 'off'
}

/** Мини-стол: бар, терминал, файлы и окно neovim. Состояние в `data-wall` / `data-nvim`, вид описан в CSS. */
function Desk({ id, wall, nvim }: DeskProps) {
  return (
    <div
      data-desk={id}
      data-wall={wall}
      data-nvim={nvim}
      className="group/desk relative grid h-full min-h-0 grid-rows-[auto_1fr] gap-1.5 overflow-hidden rounded-[11px] bg-canvas p-1.5 transition-colors duration-300 data-[wall=accent]:bg-accent/10"
    >
      <div className="flex h-3 items-center gap-1 rounded-sm bg-elevated px-1.5 font-mono text-[7px] text-ink-muted transition-colors duration-300 group-data-[wall=accent]/desk:bg-accent group-data-[wall=accent]/desk:text-on-accent">
        <i className="h-[3px] w-[9px] rounded-[2px] bg-accent group-data-[wall=accent]/desk:bg-on-accent" />
        <i className="h-[3px] w-[9px] rounded-[2px] bg-[#3a332d] group-data-[wall=accent]/desk:bg-on-accent/35" />
        <i className="h-[3px] w-[9px] rounded-[2px] bg-[#3a332d] group-data-[wall=accent]/desk:bg-on-accent/35" />
        <span className="ml-auto">19:42</span>
      </div>
      <div className="grid min-h-0 grid-cols-[1.25fr_1fr] gap-1.5 group-data-[nvim=on]/desk:grid-rows-[1fr_auto]">
        <div className="min-h-0 overflow-hidden rounded-[7px] bg-surface p-1.5 font-mono text-[7.5px] leading-[1.7] text-ink-soft inset-ring inset-ring-line-accent">
          <span className="text-accent">you@agios</span> ~ $ docker ps
          <br />
          <span className="text-accent">you@agios</span> ~ $ ▍
        </div>
        <div className="grid min-h-0 grid-cols-3 content-start gap-1 overflow-hidden rounded-[7px] bg-surface p-1.5 inset-ring inset-ring-line">
          {Array.from({ length: 6 }, (_, index) => (
            <i key={index} className={cn('aspect-square rounded-[4px]', index === 1 ? 'bg-accent-soft' : 'bg-raised')} />
          ))}
        </div>
        <div className="col-span-full hidden overflow-hidden rounded-[7px] bg-surface p-1.5 font-mono text-[7.5px] leading-[1.7] text-ink-soft inset-ring inset-ring-line group-data-[nvim=on]/desk:block group-data-[nvim=on]/desk:animate-tile max-sm:[&>p:nth-child(n+2)]:hidden">
          <p className="m-0">
            <span className="text-accent">fn</span> main() {'{'}
            <span className="text-ink-dim"> -- nvim</span>
          </p>
          <p className="m-0">&nbsp;&nbsp;println!(&quot;hi&quot;);</p>
          <p className="m-0">{'}'}</p>
        </div>
      </div>
    </div>
  )
}

/** Окно превью: три точки и тонкая рамка Line Accent; коралл целиком оставлен бару стола. */
function PreviewWindow({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-0 grid-rows-[auto_1fr] gap-1.5 rounded-xl bg-[#0d0a09] p-[7px] inset-ring inset-ring-line-accent">
      <div className="flex h-3.5 items-center gap-[5px] px-[3px]">
        <i className="size-1.5 rounded-full bg-[#e2553b]" />
        <i className="size-1.5 rounded-full bg-[#f0a93b]" />
        <i className="size-1.5 rounded-full bg-[#4a4541]" />
        <span className="ml-auto font-mono text-[8px] tracking-[0.1em] text-ink-muted uppercase">live</span>
      </div>
      {children}
    </div>
  )
}

/** Ноутбук: экран с рамкой Line Strong и основание. `data-hit` подсвечивает экран рамкой Accent. */
function Laptop({ screen, children, className }: { screen?: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn('grid min-h-0 grid-rows-[1fr_auto]', className)}>
      <div
        data-screen={screen}
        data-hit="false"
        className="relative min-h-0 rounded-[10px_10px_4px_4px] bg-[#060404] p-1.5 inset-ring inset-ring-line-strong transition-[box-shadow] duration-300 data-[hit=true]:inset-ring-accent"
      >
        {children}
      </div>
      <div className="relative -mx-2 h-2 rounded-b-lg bg-raised after:absolute after:top-0 after:left-1/2 after:h-[3px] after:w-11 after:-translate-x-1/2 after:rounded-b-[3px] after:bg-[#2c2622]" />
    </div>
  )
}

/**
 * Визуал карточки «What you tried is what you get»: три сцены подряд, как короткое видео.
 * 01 try (курсор сам правит превью) → 02 move (окно ужимается, точки бегут к ноутбуку, строки Copied)
 * → 03 yours (ноутбук с тем же столом и теми же правками). Таймлайн живёт в `mountSameSystemVisual`.
 * SSR-разметка показывает третью сцену: без JavaScript карточка остаётся законченной картинкой.
 */
export function SameSystemVisual() {
  return (
    <div ref={mountSameSystemVisual} className="absolute inset-0 cursor-pointer">
      <span data-label="" className={cn(label, 'absolute top-3.5 left-[18px] z-10 flex items-center gap-2 max-sm:left-3.5')}>
        <i data-label-dot="" data-live="false" className="size-1.5 animate-blink rounded-full bg-accent data-[live=false]:hidden" />
        <span data-label-text="">on your computer</span>
      </span>

      {/* Легенда сцен, как шаги в демо hero: активная — Accent с линией прогресса. */}
      <div role="presentation" className="absolute top-3 right-3.5 z-10 flex gap-3.5 max-sm:gap-2.5">
        {sameSystemScenes.map((name, index) => (
          <button
            key={name}
            type="button"
            tabIndex={-1}
            data-go={index}
            data-active={index === 2}
            className={cn(
              label,
              'relative pb-[5px] text-ink-dim transition-colors duration-200 after:absolute after:inset-x-0 after:bottom-0 after:h-px after:origin-left after:bg-accent after:[transform:scaleX(var(--p,0))] hover:text-ink-soft data-[active=true]:text-accent max-sm:text-[9px]',
            )}
          >
            {name}
          </button>
        ))}
      </div>

      {/* 01 · Try */}
      <div data-scene="" className={cn(scene, sides, 'invisible opacity-0')}>
        <div className={sideLeft}>
          <span className={cn(label, 'mb-1 max-sm:hidden')}>try</span>
          {CHANGES.map((change) => (
            <span
              key={change}
              data-chip=""
              data-on="false"
              className="group/chip inline-flex items-center gap-1.5 rounded-full px-[11px] py-[5px] text-[12.5px] leading-[1.3] whitespace-nowrap text-ink-soft inset-ring inset-ring-line-strong transition-[background-color,color,box-shadow] duration-200 data-[on=true]:bg-accent data-[on=true]:text-on-accent data-[on=true]:inset-ring-0"
            >
              {change}
              <CheckIcon className="hidden size-2.5 group-data-[on=true]/chip:block" />
            </span>
          ))}
        </div>
        <div className={center}>
          <PreviewWindow>
            <Desk id="preview" wall="plain" nvim="off" />
          </PreviewWindow>
        </div>
        <span className={sideRight}>Click around. It is the real system.</span>
        <svg
          data-cursor=""
          viewBox="0 0 16 18"
          aria-hidden="true"
          className="pointer-events-none absolute top-0 left-0 z-10 h-[18px] w-4 opacity-0 drop-shadow-[0_1px_1px_rgb(0_0_0/.6)] will-change-[transform,opacity]"
        >
          <path d="M1.5 1.5v13l3.4-3 2.2 5 2.6-1.1-2.2-5H12z" fill="#f6f2ec" stroke="#0b0908" strokeWidth="1.2" strokeLinejoin="round" />
        </svg>
      </div>

      {/* 02 · Move */}
      <div data-scene="" className={cn(scene, 'invisible grid grid-rows-[1fr_auto] gap-3 opacity-0')}>
        <div className="grid min-h-0 grid-cols-[1fr_64px_1fr] gap-2.5 max-sm:grid-cols-1 max-sm:grid-rows-[1fr_30px_1fr]">
          <div className="grid min-h-0 origin-center scale-[.94]">
            <PreviewWindow>
              <Desk id="thumb" wall="accent" nvim="on" />
            </PreviewWindow>
          </div>
          <div data-link="" className="relative">
            <i className="absolute inset-x-0 top-1/2 border-t-[1.5px] border-dashed border-line-strong max-sm:inset-x-auto max-sm:inset-y-0 max-sm:left-1/2 max-sm:border-t-0 max-sm:border-l-[1.5px]" />
            {Array.from({ length: PACKETS }, (_, index) => (
              <i
                key={index}
                data-packet=""
                className="absolute top-1/2 left-0 -mt-[4.5px] -ml-[4.5px] size-[9px] rounded-full bg-accent opacity-0 will-change-[transform,opacity] max-sm:top-0 max-sm:left-1/2"
              />
            ))}
          </div>
          <Laptop screen="target">
            <div className="absolute inset-1.5 grid place-content-center rounded-md border-[1.5px] border-dashed border-line-strong text-[11.5px] text-ink-dim">
              your computer
            </div>
          </Laptop>
        </div>
        <ul className="m-0 grid list-none grid-cols-4 gap-2 p-0 max-sm:grid-cols-2">
          {COPY_ROWS.map((row) => (
            <li key={row} data-row="" className={cn(label, 'grid gap-[5px] text-[9.5px] tracking-[0.14em]')}>
              {row}
              <i data-row-bar="" className="block h-0.5 origin-left rounded-px bg-accent" />
              <span data-row-status="" className="min-h-3 font-mono text-[9.5px] tracking-[0.04em] text-ok normal-case" />
            </li>
          ))}
        </ul>
      </div>

      {/* 03 · Yours — без JavaScript видна сразу */}
      <div data-scene="" className={cn(scene, sides)}>
        <div className={sideLeft}>
          {CHANGES.map((change) => (
            <span
              key={change}
              data-tag=""
              className="inline-flex items-center gap-1.5 rounded-full bg-raised px-[9px] py-[3px] text-[11.5px] whitespace-nowrap text-ink-soft"
            >
              {change}
              <b className="font-mono text-[10.5px] font-normal text-ok">kept</b>
            </span>
          ))}
        </div>
        <Laptop screen="computer" className={cn(center, 'relative')}>
          <span
            data-pill=""
            className="absolute top-2.5 right-2.5 z-10 inline-flex h-6 items-center gap-1.5 rounded-full bg-raised px-2.5 text-[11.5px] text-ink"
          >
            <i className="size-[7px] rounded-full bg-ok" />
            Installed
          </span>
          <Desk id="computer" wall="accent" nvim="on" />
        </Laptop>
        <span data-caption="" className={sideRight}>
          Same system. Nothing to redo.
        </span>
      </div>
    </div>
  )
}
