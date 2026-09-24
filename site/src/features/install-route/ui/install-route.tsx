import { Link } from '@tanstack/react-router'

import { buttonStyles } from '@/shared/ui/button'
import { CheckIcon } from '@/shared/ui/icon'

import { osChoices, routeSteps, stepTitles, targetChoices } from '../model/route'
import { useInstallRoute } from '../model/use-install-route'
import { ChoiceGroup } from './choice-group'
import { StepContent } from './step-content'

/**
 * Пульт маршрута: два вопроса слева (система и носитель), справа окно с чек-листом под ответ.
 * Коралловый штрих по периметру окна дорисовывается по отмеченным шагам — «рамка = прогресс», как в hero.
 */
export function InstallRoute() {
  const route = useInstallRoute()
  const steps = routeSteps(route.os, route.target)
  const doneCount = steps.filter((step) => route.done[step]).length
  const complete = doneCount === steps.length
  const osName = osChoices.find((choice) => choice.id === route.os)?.name ?? ''
  const targetName = route.target === 'vm' ? 'virtual machine' : 'usb stick'

  return (
    <div className="grid items-start gap-7 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)] xl:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
      <aside className="grid gap-[26px] lg:sticky lg:top-[120px]">
        <ChoiceGroup
          index="01"
          legend="You’re on"
          name="install-os"
          choices={osChoices}
          value={route.os}
          detected={route.detected}
          onChange={route.setOs}
        />
        <ChoiceGroup
          index="02"
          legend="Boot it from"
          name="install-target"
          choices={targetChoices}
          value={route.target}
          onChange={route.setTarget}
        />
        <div className="rounded-2xl bg-surface p-[18px] inset-ring inset-ring-line">
          <p className="font-mono text-[10.5px] tracking-[0.16em] text-ink-muted uppercase">Before you begin</p>
          <ul className="mt-2.5 grid gap-2 text-sm text-ink-soft">
            {[
              'A 64-bit PC with UEFI. Installing on real hardware is still experimental.',
              'An agent: ChatGPT sign-in, an API key, local Ollama or a compatible endpoint.',
              'A backup of anything on the target drive.',
            ].map((item) => (
              <li key={item} className="flex gap-2.5">
                <span aria-hidden="true" className="mt-2 size-[5px] shrink-0 rounded-full bg-accent" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <section aria-label="Install steps" className="relative min-w-0 rounded-2xl bg-[#0d0a09] inset-ring inset-ring-line">
        {/* Рамка-прогресс: svg утоплен на половину штриха, поэтому rect может занимать 100% без замеров. */}
        <svg aria-hidden="true" className="pointer-events-none absolute inset-[0.75px] size-[calc(100%-1.5px)] overflow-visible">
          <rect
            width="100%"
            height="100%"
            rx="15.25"
            pathLength={1}
            style={{ strokeDashoffset: 1 - doneCount / steps.length }}
            className="fill-none stroke-accent stroke-[1.5] transition-[stroke-dashoffset] duration-700 ease-in-out-strong [stroke-dasharray:1]"
          />
        </svg>

        <div className="flex items-center gap-3.5 px-5 py-4">
          <div aria-hidden="true" className="flex gap-[7px]">
            <span className="size-2.5 rounded-full bg-[#e2553b]" />
            <span className="size-2.5 rounded-full bg-[#f0a93b]" />
            <span className="size-2.5 rounded-full bg-[#4a4541]" />
          </div>
          <span className="mx-auto max-w-[60%] truncate rounded-full bg-elevated px-3.5 py-[5px] font-mono text-[11.5px] text-ink-muted lowercase inset-ring inset-ring-line">
            route · {osName} → {targetName}
          </span>
          <span aria-live="polite" className="font-mono text-[10.5px] tracking-[0.16em] whitespace-nowrap text-ink-muted uppercase tabular-nums">
            {doneCount} / {steps.length} done
          </span>
        </div>

        <ol className="sm:px-2 sm:pb-2">
          {steps.map((step, index) => {
            const done = Boolean(route.done[step])
            return (
              <li
                key={step}
                data-done={done}
                className="group/step grid grid-cols-[34px_minmax(0,1fr)] gap-x-2.5 gap-y-1 border-t border-line px-3.5 py-[18px] first:border-t-0 sm:grid-cols-[44px_minmax(0,1fr)] sm:gap-x-3.5 sm:px-4 sm:py-5"
              >
                <button
                  type="button"
                  aria-pressed={done}
                  aria-label={`Mark “${stepTitles[step]}” as done`}
                  onClick={() => route.setDone(step, !done)}
                  className="grid size-7 place-items-center rounded-full font-mono text-xs text-ink-muted inset-ring-[1.5px] inset-ring-ink-dim transition-[box-shadow,background-color,color,scale] duration-150 ease-out-strong hover:text-ink hover:inset-ring-accent active:scale-[0.92] aria-pressed:bg-accent aria-pressed:text-on-accent aria-pressed:inset-ring-accent sm:size-[30px]"
                >
                  {done ? <CheckIcon className="size-3.5" /> : index + 1}
                </button>
                <h3 className="mt-0.5 font-serif text-[23px] leading-[1.2] tracking-[-0.014em] transition-colors duration-300 group-data-[done=true]/step:text-ink-muted">
                  {stepTitles[step]}
                </h3>
                <div className="col-span-2 mt-1.5 grid grid-cols-[minmax(0,1fr)] gap-3 text-[15px] leading-[1.6] text-ink-soft sm:col-span-1 sm:col-start-2 [&>p]:max-w-[64ch]">
                  <StepContent step={step} os={route.os} target={route.target} onDone={() => route.setDone(step, true)} />
                </div>
              </li>
            )
          })}
        </ol>

        {complete && (
          <div className="m-2 mt-0 grid grid-cols-[auto_1fr] items-center gap-[18px] rounded-xl bg-surface p-[22px] inset-ring inset-ring-line-accent motion-safe:animate-rise sm:grid-cols-[auto_1fr_auto]">
            <svg viewBox="0 0 56 56" aria-hidden="true" className="size-14 fill-none stroke-accent">
              <circle cx="28" cy="28" r="25" className="stroke-line-strong stroke-[1.5]" />
              <circle
                cx="28"
                cy="28"
                r="25"
                pathLength={1}
                transform="rotate(-90 28 28)"
                className="stroke-[1.5] [stroke-dasharray:1] motion-safe:animate-draw"
              />
              <path d="M19 28.5l6 6 12-13" pathLength={1} className="stroke-2 [stroke-dasharray:1] motion-safe:animate-draw motion-safe:[animation-delay:0.8s]" />
            </svg>
            <div>
              <h3 className="font-serif text-2xl tracking-[-0.014em]">Ready to boot.</h3>
              <p className="mt-0.5 text-[14.5px] text-ink-muted">
                Firefox opens the installer at localhost:8787 by itself. Nothing on your disk has changed.
              </p>
            </div>
            <div className="col-span-2 flex flex-wrap gap-3 sm:col-span-1">
              <Link
                to="/docs/$slug"
                params={{ slug: 'getting-started' }}
                hash="connect"
                className={buttonStyles({ variant: 'outline', size: 'sm' })}
              >
                Next: connect your agent
              </Link>
              <button
                type="button"
                onClick={route.reset}
                className="px-2 font-mono text-[11px] tracking-[0.12em] text-ink-muted uppercase transition-colors duration-200 hover:text-ink"
              >
                Start over
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
