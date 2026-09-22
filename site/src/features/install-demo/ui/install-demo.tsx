import { cn } from '@/shared/lib/cn'
import { Sunburst } from '@/shared/ui/sunburst'

import { mountInstallDemo } from '../lib/mount-install-demo'
import { BuildScene, InstallScene, ListenScene, PreviewScene, Scene } from './scenes'

const STEPS = ['Listen', 'Preview', 'Build', 'Install'] as const
/** Подписи состояния: по одной на шаг, у Build две (пока кольцо крутится и после галочки). */
const STATES = ['listening', 'live preview', 'building', 'moving', 'installed'] as const

interface InstallDemoProps {
  id?: string
  className?: string
}

/**
 * Окно установщика: четыре сцены подряд как один ролик — слушаю → превью → сборка → установка.
 * Рамка Line 1px, а коралловый штрих по периметру дорисовывается в темпе шагов (рамка = прогресс).
 */
export function InstallDemo({ id, className }: InstallDemoProps) {
  return (
    <div id={id} ref={mountInstallDemo} className={cn('relative w-full scroll-mt-28 text-left', className)}>
      <div
        role="tablist"
        aria-label="How it works"
        className="absolute top-5 right-6 z-10 flex gap-[18px] max-sm:top-4 max-sm:right-4 max-sm:gap-2.5"
      >
        {STEPS.map((step, index) => (
          <button
            key={step}
            type="button"
            role="tab"
            data-demo-step=""
            data-active={index === 0}
            data-done="false"
            aria-selected={index === 0}
            className="flex items-center gap-[7px] font-mono text-[10.5px] tracking-[0.16em] text-ink-dim uppercase transition-colors duration-200 hover:text-ink-soft data-[active=true]:text-accent data-[done=true]:text-ink-muted max-sm:gap-1.5 max-sm:text-[9px] max-sm:tracking-widest"
          >
            <i aria-hidden="true" className="size-[5px] rounded-full bg-current" />
            {step}
          </button>
        ))}
      </div>

      <div className="relative min-h-[clamp(436px,calc(100svh_-_575px),470px)] overflow-hidden rounded-2xl bg-[#0d0a09] inset-ring inset-ring-line max-sm:min-h-[450px]">
        <svg data-rim="" aria-hidden="true" className="pointer-events-none absolute inset-0 z-[4] size-full text-accent">
          <rect
            data-rim-path=""
            x="0.75"
            y="0.75"
            rx="15.5"
            ry="15.5"
            pathLength={1}
            className="fill-none stroke-current stroke-[1.5] [stroke-dasharray:1] [stroke-dashoffset:1]"
          />
        </svg>
        <Sunburst
          variant="disc"
          className="pointer-events-none absolute top-1/2 -right-[110px] size-[280px] -translate-y-1/2 text-accent opacity-[0.32] max-sm:hidden"
        />
        <div aria-hidden="true" className="flex gap-2.5 px-6 pt-[22px] max-sm:px-4 max-sm:pt-[18px]">
          <i className="size-[9px] rounded-full bg-[#e2553b]" />
          <i className="size-[9px] rounded-full bg-[#f0a93b]" />
          <i className="size-[9px] rounded-full bg-[#4a4541]" />
        </div>
        <p
          aria-hidden="true"
          className="absolute top-[22px] left-1/2 z-[3] m-0 flex -translate-x-1/2 items-center gap-2 font-mono text-[10.5px] tracking-[0.16em] text-ink-muted uppercase max-sm:top-[19px] max-sm:left-[78px] max-sm:translate-x-0"
        >
          <i
            data-status-dot=""
            data-live="true"
            className="size-1.5 rounded-full bg-accent data-[live=false]:bg-ink-dim data-[live=true]:animate-blink"
          />
          <span className="grid">
            {STATES.map((state, index) => (
              <span
                key={state}
                data-state=""
                className={cn('col-start-1 row-start-1 whitespace-nowrap', index !== 0 && 'invisible opacity-0')}
              >
                {state}
              </span>
            ))}
          </span>
        </p>

        <Scene active label="Listen">
          <ListenScene />
        </Scene>
        <Scene active={false} label="Preview">
          <PreviewScene />
        </Scene>
        <Scene active={false} label="Build">
          <BuildScene />
        </Scene>
        <Scene active={false} label="Install">
          <InstallScene />
        </Scene>
      </div>
    </div>
  )
}
