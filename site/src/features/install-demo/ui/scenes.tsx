import type { ReactNode } from 'react'

import { spokenSentence, spokenToolIds, tools, type Tool } from '@/entities/tool'
import { cn } from '@/shared/lib/cn'
import { ArrowRightIcon, CheckIcon } from '@/shared/ui/icon'
import { ProgressRing } from '@/shared/ui/progress-ring'
import { MicButton, SpokenSentence, Wave } from '@/shared/ui/voice'

const WAVE_BARS = 84
const EDITOR_LINES = [
  { width: '55%', indent: 0 },
  { width: '70%', indent: 10, hot: true },
  { width: '40%', indent: 20 },
  { width: '62%', indent: 10 },
  { width: '30%', indent: 0 },
] as const
const INSTALL_ROWS = [
  { label: 'The system you just tried', status: 'Copied' },
  { label: 'Your files and settings', status: 'Kept' },
  { label: 'Starts on its own', status: 'Checked' },
] as const

const spokenTools = spokenToolIds.map((id) => tools.find((tool) => tool.id === id)).filter((tool): tool is Tool => !!tool)
/** Лейблы вокруг кольца сборки: четыре сказанных слова и Waybar, который агент добавил сам. По часовой стрелке от левого. */
const BUILD_LABELS = [...spokenTools, tools.find((tool) => tool.id === 'waybar')].filter((tool): tool is Tool => !!tool)
/** Углы лейблов (градусы, 0 — справа, по часовой стрелке): слева → вверху слева → сверху → вверху справа → справа. */
const BUILD_ANGLES = [180, 225, 270, 315, 0] as const

interface SceneProps {
  active: boolean
  label: string
  children: ReactNode
}

/** Слой сцены. Смену сцен ведёт GSAP (`autoAlpha` + сдвиг); SSR показывает первую. */
export function Scene({ active, label, children }: SceneProps) {
  return (
    <div
      data-demo-scene=""
      inert={!active}
      role="tabpanel"
      aria-label={label}
      className={cn(
        'absolute inset-x-0 top-[72px] bottom-[30px] px-7 will-change-[transform,opacity] max-sm:top-16 max-sm:bottom-4 max-sm:px-3.5',
        !active && 'invisible opacity-0',
      )}
    >
      {children}
    </div>
  )
}

/** 01 · Listening — та же сцена, что в «Say it in words», в масштабе hero: микрофон на оси волны, фраза под ней. */
export function ListenScene() {
  return (
    <div className="relative h-full">
      <div className="absolute inset-x-0 top-1/2 grid -translate-y-1/2 gap-[30px] max-sm:gap-[22px]">
        <div className="flex items-center gap-[22px] max-sm:gap-3">
          <MicButton className="size-[34px] flex-none max-sm:size-[30px]" />
          <Wave bars={WAVE_BARS} className="h-20 min-w-0 flex-1 max-sm:h-16" />
        </div>
        <SpokenSentence
          words={spokenSentence}
          className="px-2 text-[length:clamp(22px,3vw,30px)] leading-[1.3] tracking-[-0.012em] max-sm:text-xl"
        />
      </div>
    </div>
  )
}

/** Курсор для сцены Preview: остриё в точке (0,0) svg. */
function Cursor() {
  return (
    <svg
      data-cursor=""
      viewBox="0 0 24 24"
      aria-hidden="true"
      className="absolute top-1/2 left-1/2 size-[22px] -mt-[3px] -ml-[5px] will-change-[transform,opacity]"
    >
      <path
        d="M5.5 3.2v17.3l4.3-3.9 2.8 6 2.8-1.3-2.7-5.9 5.9-.2z"
        className="fill-ink stroke-canvas stroke-[1.4]"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function Tile({ id, className, children }: { id: string; className?: string; children: ReactNode }) {
  return (
    <div
      data-tile=""
      data-focus="false"
      className={cn(
        'relative overflow-hidden rounded-xl bg-canvas p-3.5 inset-ring inset-ring-line transition-[box-shadow] duration-300 ease-out-strong data-[focus=true]:inset-ring-line-accent',
        className,
      )}
    >
      <span className="mb-1.5 block font-mono text-[9.5px] tracking-[0.08em] text-ink-dim uppercase">{id}</span>
      {children}
    </div>
  )
}

function Prompt({ children }: { children?: ReactNode }) {
  return (
    <p data-line="" className="m-0 whitespace-nowrap">
      <span className="text-accent">you@agios</span> ~ $ {children}
    </p>
  )
}

/** 02 · Preview — мини-стол Hyprland: терминал печатает, файлы подсвечиваются, фокус гуляет по окнам. */
export function PreviewScene() {
  return (
    <div className="relative h-full overflow-hidden rounded-[14px] bg-elevated">
      <div className="mx-2 mt-2 flex h-[26px] items-center gap-2 rounded-[9px] bg-canvas px-3 font-mono text-[10.5px] text-ink-soft">
        <span className="flex gap-1">
          <i className="h-1.5 w-[15px] rounded-[3px] bg-accent" />
          <i className="size-1.5 rounded-full bg-[#444]" />
          <i className="size-1.5 rounded-full bg-[#444]" />
        </span>
        hyprland
        <span className="ml-auto">19:42</span>
      </div>
      <div className="absolute inset-x-2 top-[42px] bottom-2 grid grid-cols-[1.25fr_1fr] grid-rows-[1fr_1fr] gap-2 max-sm:grid-cols-1">
        <Tile id="terminal" className="row-span-2 font-mono text-[11.5px] leading-[1.75] text-ink-soft">
          <Prompt>nvim .</Prompt>
          <Prompt>docker ps</Prompt>
          <p data-line="" className="m-0 whitespace-nowrap text-[#7ec98f]">
            CONTAINER ID&nbsp;&nbsp;IMAGE&nbsp;&nbsp;STATUS
          </p>
          <Prompt>
            <i className="inline-block h-3 w-1.5 animate-blink bg-ink-soft align-[-2px] [animation-timing-function:steps(2)]" />
          </Prompt>
        </Tile>
        <Tile id="files" className="max-sm:hidden">
          <div className="grid grid-cols-3 gap-[7px]">
            {Array.from({ length: 6 }, (_, index) => (
              <i
                key={index}
                data-file=""
                data-hot="false"
                className="aspect-[1.4] rounded-[7px] bg-raised transition-[background-color] duration-400 data-[hot=true]:bg-accent-soft"
              />
            ))}
          </div>
        </Tile>
        <Tile id="editor" className="max-sm:hidden">
          {EDITOR_LINES.map((line) => (
            <i
              key={line.width}
              data-editor-line=""
              style={{ width: line.width, marginLeft: line.indent }}
              className={cn('mb-1.5 block h-[5px] origin-left rounded-[3px] bg-raised', 'hot' in line && 'bg-accent-soft')}
            />
          ))}
        </Tile>
      </div>
      <span className="absolute right-4 bottom-4 inline-flex h-7 items-center gap-[7px] rounded-full bg-raised px-3 text-[12.5px]">
        <i className="size-[7px] animate-blink rounded-full bg-[#5fd38a]" />
        Live preview
      </span>
      {/* В конце сцены снизу по центру появляется кнопка, курсор подъезжает и нажимает — переход к сборке. */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2">
        <span
          data-cta=""
          className="inline-flex h-10 items-center gap-2 rounded-[7px] bg-accent px-5 font-mono text-[13.5px] font-medium tracking-[0.02em] whitespace-nowrap text-on-accent will-change-[transform,opacity] [&_svg]:size-[15px]"
        >
          Get this setup <ArrowRightIcon />
        </span>
        <Cursor />
      </div>
    </div>
  )
}

/** 03 · Build — кольцо собирает систему из сказанных слов; на галочке — «Build is ready, moving to your computer». */
export function BuildScene() {
  return (
    <div className="grid h-full place-content-center justify-items-center gap-4 text-center">
      {/* Кольцо в нижней половине площадки; лейблы стоят на дуге радиусом --r над ним и по бокам. */}
      <div className="relative h-[200px] w-full [--cy:150px] [--r:120px] max-sm:h-[170px] max-sm:[--cy:124px] max-sm:[--r:98px]">
        <ProgressRing className="absolute top-(--cy) left-1/2 size-24 -translate-x-1/2 -translate-y-1/2" />
        <ul className="m-0 list-none p-0 font-mono text-xs tracking-[0.04em] text-ink-soft max-sm:text-[11px]">
          {BUILD_LABELS.map((tool, index) => {
            const angle = ((BUILD_ANGLES[index] ?? 0) * Math.PI) / 180
            const cos = Math.cos(angle).toFixed(3)
            const sin = Math.sin(angle).toFixed(3)
            return (
              // Позиционирует внешний <li>; GSAP анимирует внутренний <span> (правило Tailwind v4 + GSAP).
              <li
                key={tool.id}
                style={{ left: `calc(50% + ${cos} * var(--r))`, top: `calc(var(--cy) + ${sin} * var(--r))` }}
                className="absolute -translate-x-1/2 -translate-y-1/2"
              >
                <span data-read="" className="flex items-center gap-1.5 whitespace-nowrap will-change-[transform,opacity]">
                  <i className="size-[5px] rounded-full bg-accent" />
                  {tool.label.toLowerCase()}
                  <CheckIcon data-read-check="" className="size-[11px] text-accent" />
                </span>
              </li>
            )
          })}
        </ul>
      </div>
      <p
        data-ready=""
        className="m-0 px-3 font-serif text-[length:clamp(20px,2.6vw,26px)] leading-[1.2] tracking-[-0.015em] text-balance"
      >
        Build is ready, moving to your computer
      </p>
    </div>
  )
}

/** 04 · Install — система установлена. */
export function InstallScene() {
  return (
    <div className="grid h-full place-items-center text-center">
      <div className="grid w-full max-w-[452px] justify-items-center gap-3.5">
        <div data-install-mark="" className="relative">
          <svg viewBox="0 0 76 76" fill="none" strokeWidth="5" strokeLinecap="round" className="size-[74px] -rotate-90">
            <circle cx="38" cy="38" r="32" className="stroke-[#241d18]" />
            <circle data-install-ring="" cx="38" cy="38" r="32" className="stroke-accent [stroke-dasharray:201] [stroke-dashoffset:201]" />
          </svg>
          <CheckIcon data-install-check="" className="absolute inset-0 m-auto size-7 text-ink" />
        </div>
        <h3 data-install-title="" className="font-serif text-[29px] tracking-[-0.015em] max-sm:text-2xl">
          Installing your system
        </h3>
        <ul className="grid w-full gap-[7px]">
          {INSTALL_ROWS.map((row) => (
            <li
              key={row.label}
              data-install-row=""
              className="flex items-center justify-between rounded-[10px] bg-elevated px-5 py-[11px] text-ink-soft max-sm:px-3.5 max-sm:py-2.5 max-sm:text-sm"
            >
              {row.label}
              <span className="text-ok">{row.status}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
