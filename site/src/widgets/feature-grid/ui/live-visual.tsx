import type { ReactNode } from 'react'

import { cn } from '@/shared/lib/cn'

import { mountLiveVisual } from '../lib/mount-live-visual'
import { liveRequests, restRequestIndex, type LiveWindow } from '../model/live-requests'

const WAVE_DELAYS = ['0s', '.12s', '.24s', '.36s'] as const

/**
 * Токены мини-стола. Светлая тема живёт только внутри превью: это содержимое пользовательской системы,
 * а не поверхность сайта, поэтому правило «единственная светлая поверхность — футер» не нарушено.
 */
const deskTokens = cn(
  '[--d-bar:var(--color-elevated)] [--d-win:var(--color-surface)] [--d-ink:var(--color-ink-soft)] [--d-muted:var(--color-ink-dim)]',
  '[--d-raised:var(--color-raised)] [--d-line:var(--color-line)] [--d-ok:#7ec98f] [--d-hot:var(--color-accent-soft)] [--d-ws:#444]',
  'data-[theme=light]:[--d-bar:#e6dbca] data-[theme=light]:[--d-win:#faf6ef] data-[theme=light]:[--d-ink:#0f0d0b] data-[theme=light]:[--d-muted:#7a6a55]',
  'data-[theme=light]:[--d-raised:#e6dbca] data-[theme=light]:[--d-line:rgb(15_13_11/.12)] data-[theme=light]:[--d-ok:#1f9a63]',
  'data-[theme=light]:[--d-hot:rgb(255_106_61/.22)] data-[theme=light]:[--d-ws:#c9bca8]',
)

/**
 * Единая перекраска: все цвета стола переходят за 500 мс по одной кривой. Разные длительности и кривые у соседей
 * читаются как рваная смена темы. Движение (высота бара, зазоры, радиусы, рамка фокуса) живёт на своих кривых.
 */
const themed = 'transition-colors duration-500 ease-theme'

const swatch = cn('h-[5px] rounded-[3px] bg-(--d-raised)', themed)

function Window({ id, focus, children }: { id: LiveWindow; focus?: boolean; children: ReactNode }) {
  return (
    <div
      data-window={id}
      data-focus={focus ?? false}
      className={cn(
        'grid min-h-0 grid-rows-[auto_1fr] gap-[5px] overflow-hidden rounded-lg bg-(--d-win) p-2 inset-ring inset-ring-(--d-line)',
        '[transition:background-color_.5s_var(--ease-theme),box-shadow_.3s_var(--ease-out-strong),border-radius_.4s_var(--ease-out-strong)]',
        'data-[focus=true]:inset-ring-[1.5px] data-[focus=true]:inset-ring-accent',
        'group-data-[rice=true]/frame:rounded-[14px] group-data-[rice=true]/frame:data-[focus=true]:inset-ring-2',
        'group-data-[bouncy=true]/frame:[transition:background-color_.5s_var(--ease-theme),box-shadow_.45s_cubic-bezier(.34,1.56,.64,1),border-radius_.4s_var(--ease-out-strong)]',
        id === 'terminal' && 'row-span-2',
      )}
    >
      <span className={cn('font-mono text-[9.5px] tracking-[0.08em] text-(--d-muted) uppercase', themed)}>{id}</span>
      <div className="grid min-h-0 content-start gap-[5px] overflow-hidden [mask-image:linear-gradient(#000_calc(100%-12px),transparent)]">
        {children}
      </div>
    </div>
  )
}

function Prompt({ children }: { children: ReactNode }) {
  return (
    <p className={cn('m-0 font-mono text-[9.5px] leading-[1.4] whitespace-nowrap text-(--d-ink)', themed)}>
      <span className="text-accent">$</span> {children}
    </p>
  )
}

/**
 * Визуал карточки «Try it live first»: строка запроса над окном превью, как в hero, и мини-стол, который меняется от слов.
 * Пять запросов по кругу (тёмная тема → без панели → другой райсинг → прыгучие окна → назад к светлой).
 * Состояние стола хранится в `data-*` на рамке, вся смена вида описана в CSS; логика в `mountLiveVisual`.
 * SSR-разметка показывает результат последнего запроса: светлый стол и фразу «light theme, bar back».
 */
export function LiveVisual() {
  return (
    <div ref={mountLiveVisual} className="absolute inset-0">
      <button
        type="button"
        tabIndex={-1}
        data-say=""
        data-rec="false"
        className="group/say absolute inset-x-[22px] top-2 z-10 flex h-7 items-center gap-[9px] rounded-[7px] px-1 text-left transition-transform duration-150 ease-out-strong active:scale-[.985]"
      >
        <span className="flex h-3.5 flex-none items-center gap-0.5">
          {WAVE_DELAYS.map((delay) => (
            <i
              key={delay}
              style={{ animationDelay: delay }}
              className="h-1 w-0.5 rounded-px bg-accent group-data-[rec=true]/say:animate-wave"
            />
          ))}
        </span>
        <span className="relative h-full min-w-0 flex-1">
          {liveRequests.map((request, index) => (
            <span
              key={request.effect}
              data-phrase=""
              hidden={index !== restRequestIndex}
              className="absolute inset-0 flex items-center gap-[.28em] font-serif text-[15.5px] leading-none tracking-[-0.01em] whitespace-nowrap text-ink italic"
            >
              {request.words.map((word) => (
                <span
                  key={word.text}
                  data-word=""
                  data-on={index === restRequestIndex}
                  className={cn('opacity-0 transition-opacity duration-200 data-[on=true]:opacity-100', 'hot' in word && 'text-accent')}
                >
                  {word.text}
                </span>
              ))}
            </span>
          ))}
        </span>
        <span data-count="" className="ml-auto font-mono text-[9.5px] tracking-[0.14em] text-ink-dim uppercase">
          {liveRequests.length} / {liveRequests.length}
        </span>
      </button>

      <div
        data-frame=""
        data-theme="light"
        data-bar="on"
        data-rice="false"
        data-bouncy="false"
        className={cn(
          'group/frame absolute inset-x-[22px] top-11 bottom-0 grid grid-rows-[auto_1fr] overflow-hidden rounded-t-[14px] bg-(--d-win) inset-ring inset-ring-(--d-line) [transition:background-color_.5s_var(--ease-theme),box-shadow_.5s_var(--ease-theme)]',
          deskTokens,
        )}
      >
        <div className="flex h-[22px] items-center gap-2 overflow-hidden bg-(--d-bar) px-2.5 font-mono text-[10.5px] whitespace-nowrap text-(--d-ink) [transition:height_.45s_var(--ease-out-strong),background-color_.5s_var(--ease-theme),color_.5s_var(--ease-theme)] group-data-[bar=off]/frame:h-0">
          <span className="flex gap-1">
            <i className="h-1.5 w-[15px] rounded-[3px] bg-accent" />
            <i className={cn('size-1.5 rounded-full bg-(--d-ws)', themed)} />
            <i className={cn('size-1.5 rounded-full bg-(--d-ws)', themed)} />
          </span>
          <span className={cn('text-(--d-muted)', themed)}>hyprland</span>
          <span className={cn('ml-auto text-(--d-muted)', themed)}>19:42</span>
        </div>

        <div className="grid min-h-0 grid-cols-[1.2fr_1fr] grid-rows-[1fr_1fr] gap-1.5 px-[7px] pt-[7px] transition-[gap] duration-400 ease-out-strong group-data-[rice=true]/frame:gap-3">
          <Window id="terminal" focus>
            <Prompt>nvim .</Prompt>
            <Prompt>docker ps</Prompt>
            <p className={cn('m-0 font-mono text-[9.5px] leading-[1.4] text-(--d-ok)', themed)}>2 running</p>
            <Prompt>
              <i className={cn('inline-block h-[9px] w-[5px] animate-blink bg-(--d-ink) align-[-1px] [animation-timing-function:steps(2)]', themed)} />
            </Prompt>
          </Window>
          <Window id="files">
            <div className="grid grid-cols-3 gap-[5px]">
              {Array.from({ length: 6 }, (_, index) => (
                <i
                  key={index}
                  className={cn('h-[13px] rounded-[5px]', themed, index === 1 ? 'bg-(--d-hot)' : 'bg-(--d-raised)')}
                />
              ))}
            </div>
          </Window>
          <Window id="editor">
            <i className={cn(swatch, 'w-[55%]')} />
            <i className={cn(swatch, 'ml-2 w-[70%] bg-(--d-hot)')} />
            <i className={cn(swatch, 'ml-4 w-[40%]')} />
            <i className={cn(swatch, 'ml-2 w-[62%]')} />
            <i className={cn(swatch, 'w-[30%]')} />
          </Window>
        </div>
      </div>

      <span className="absolute right-3.5 bottom-3.5 z-10 inline-flex h-7 items-center gap-[7px] rounded-full bg-raised px-3 text-[12.5px] text-ink">
        <i className="size-[7px] animate-blink rounded-full bg-[#5fd38a]" />
        Live preview
      </span>
    </div>
  )
}
