import { Fragment } from 'react'

import { tools } from '@/entities/tool'
import { cn } from '@/shared/lib/cn'

import { mountArchWay } from '../lib/mount-arch-way'
import { archSteps, wikiPages } from '../model/arch-steps'
import { setups } from '../model/setups'

const ID = 'arch-way'
const labelById = new Map(tools.map((tool) => [tool.id, tool.label]))
const label = 'font-mono text-[10.5px] tracking-[0.16em] text-ink-muted uppercase'
const pane = 'flex min-h-[340px] flex-col rounded-xl px-[18px] py-4 max-md:min-h-0'

/**
 * Визуал карточки «Arch was never this easy»: обычный Arch против одной фразы. Сверху вкладки реальных наборов
 * (`model/setups`, все в один ряд), ниже две панели: слева шаги, которые обычно делают руками (`model/arch-steps`),
 * справа — та же система одной фразой. SSR-разметка — законченная картинка: все наборы в разметке, виден первый,
 * шаги уже вычеркнуты. Смену наборов, автопролистывание и сцену вычёркивания ведёт `mountArchWay`.
 */
export function ArchWayVisual() {
  return (
    <div ref={mountArchWay} className="p-[18px] max-sm:p-3">
      <div
        role="tablist"
        aria-label="Setups"
        className="mb-4 flex gap-1 overflow-x-auto [scrollbar-width:none] max-sm:-mx-3 max-sm:px-3 [&::-webkit-scrollbar]:hidden"
      >
        {setups.map((setup, index) => (
          <button
            key={setup.name}
            type="button"
            role="tab"
            id={`${ID}-tab-${index}`}
            aria-controls={`${ID}-panel-${index}`}
            aria-selected={index === 0}
            tabIndex={index === 0 ? 0 : -1}
            data-arch-tab=""
            className="h-[30px] shrink-0 rounded-full px-[11px] font-mono text-[11.5px] whitespace-nowrap text-ink-muted inset-ring inset-ring-line-strong transition-[color,background-color,box-shadow] duration-200 hover:text-ink hover:inset-ring-line-accent aria-selected:bg-accent-soft aria-selected:text-accent aria-selected:inset-ring-line-accent"
          >
            {setup.name}
          </button>
        ))}
      </div>

      {setups.map((setup, index) => {
        const steps = archSteps(setup)
        const words = setup.ids.map((id) => labelById.get(id) ?? id)
        return (
          <div
            key={setup.name}
            role="tabpanel"
            id={`${ID}-panel-${index}`}
            aria-labelledby={`${ID}-tab-${index}`}
            hidden={index !== 0}
            data-arch-panel=""
            className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] gap-3.5 max-md:grid-cols-1"
          >
            <section aria-label="The usual Arch way" className={cn(pane, 'bg-elevated inset-ring inset-ring-line')}>
              <div className="mb-3 flex items-center justify-between gap-3">
                <span className={label}>The usual Arch way</span>
                <span className={label}>{steps.length} steps</span>
              </div>
              <ol className="grid gap-[3px] max-md:max-h-[190px] max-md:overflow-hidden max-md:[mask-image:linear-gradient(#000_70%,transparent)]">
                {steps.map((step, k) => (
                  <li
                    key={step}
                    data-arch-step=""
                    className="grid grid-cols-[26px_1fr] gap-1.5 font-mono text-[12.5px] leading-[1.45] text-ink-dim"
                  >
                    <span aria-hidden="true">{String(k + 1).padStart(2, '0')}</span>
                    {/* Зачёркивание — фон строки: у перенесённого шага оно идёт по каждой строке, от первой к последней. */}
                    <span className="min-w-0">
                      <span
                        data-arch-text=""
                        className="bg-[linear-gradient(var(--color-ink-dim),var(--color-ink-dim))] bg-[size:100%_1px] bg-[position:0_58%] bg-no-repeat"
                      >
                        {step}
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
              <p className="mt-auto flex justify-between gap-3 pt-3 font-mono text-xs text-ink-dim max-md:pt-4">
                <span>by hand, with the wiki open</span>
                <b className="font-normal text-ink-soft">~{wikiPages(setup)} wiki pages</b>
              </p>
            </section>

            <section aria-label="With AGIOS" className={cn(pane, 'bg-surface inset-ring inset-ring-line-accent')}>
              <div className="mb-3 flex items-center justify-between gap-3">
                <span className={cn(label, 'flex items-center gap-2')}>
                  <i className="size-1.5 animate-blink rounded-full bg-accent" />
                  With AGIOS
                </span>
                <span
                  data-arch-one=""
                  className="inline-flex h-6 items-center rounded-full bg-accent px-2.5 font-mono text-[11px] font-medium tracking-[0.06em] text-on-accent"
                >
                  1 sentence
                </span>
              </div>
              <p className="mt-1.5 font-serif text-[length:clamp(26px,3.2vw,40px)] leading-[1.18] tracking-[-0.02em] text-ink">
                {words.map((word, k) => (
                  <Fragment key={word}>
                    <span data-arch-word="" className="inline-block text-accent italic">
                      {word}
                      {k < words.length - 2 ? ',' : k === words.length - 1 ? '.' : ''}
                    </span>
                    {k === words.length - 2 ? ' and ' : ' '}
                  </Fragment>
                ))}
              </p>
              <div className="mt-auto grid gap-1.5 pt-[18px]">
                {[
                  ['Tried in the live preview', 'yours to click around'],
                  ['Installed exactly as tried', 'nothing to redo'],
                ].map(([title, status]) => (
                  <div
                    key={title}
                    className="flex h-9 items-center justify-between gap-3 rounded-[10px] bg-elevated px-3 text-[13.5px] text-ink-soft"
                  >
                    {title}
                    <span className="font-mono text-[11px] text-ok max-sm:hidden">✓ {status}</span>
                  </div>
                ))}
              </div>
            </section>
          </div>
        )
      })}
    </div>
  )
}
