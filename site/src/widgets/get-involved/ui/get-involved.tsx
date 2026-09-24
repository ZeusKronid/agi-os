import { sectionIds, siteConfig } from '@/shared/config'
import { cn } from '@/shared/lib/cn'
import { Container } from '@/shared/ui/container'
import { ArrowRightIcon } from '@/shared/ui/icon'
import { Reveal } from '@/shared/ui/reveal'
import { SectionHeading } from '@/shared/ui/section-heading'
import { Sunburst } from '@/shared/ui/sunburst'

import { mountSunrise } from '../lib/mount-sunrise'

type Tone = 'fill' | 'line'

interface ActionCardProps {
  tone: Tone
  eyebrow: string
  href: string
  title: string
  text: string
  action: string
  /** Вторичные пути: ссылки у `fill`, подписи «куда идут деньги» у `line`. */
  extras: { label: string; href?: string }[]
  extrasLabel: string
}

// Восход `split` шириной 600px (масштаб 600/640 от viewBox): центр стоит на шве между карточками,
// основание дуги — на нижнем крае. Каждая карточка обрезает свою половину. В стопке (< lg) шов
// горизонтальный: верхняя карточка несёт восход, нижняя — его отражение.
const sunStyles: Record<Tone, string> = {
  fill: 'left-[calc(100%+8px-300px)] text-on-accent opacity-[0.42] group-has-[[data-tone=line]:hover]/involved:opacity-[0.22] max-lg:bottom-[-15px]',
  line: 'left-[calc(-8px-300px)] text-accent group-has-[[data-tone=fill]:hover]/involved:opacity-[0.38] max-lg:top-[-15px] max-lg:bottom-auto max-lg:-scale-y-100 max-lg:opacity-50',
}

function ActionCard({ tone, eyebrow, href, title, text, action, extras, extrasLabel }: ActionCardProps) {
  const fill = tone === 'fill'
  return (
    <Reveal className="h-full">
      <article
        data-tone={tone}
        className={cn(
          'group/cta relative isolate flex h-full min-h-[340px] flex-col overflow-hidden rounded-2xl p-8 transition-[translate,background-color,box-shadow] duration-300 ease-out-strong focus-within:-translate-y-1 hover:-translate-y-1 max-sm:min-h-[300px] max-sm:p-[26px]',
          fill
            ? 'bg-accent text-on-accent hover:bg-accent-hover'
            : 'bg-surface inset-ring inset-ring-line-accent focus-within:inset-ring-accent hover:inset-ring-accent lg:items-end lg:text-right',
        )}
      >
        <Sunburst
          variant="split"
          className={cn(
            'pointer-events-none absolute bottom-[-9.5px] -z-10 h-[231px] w-[600px] transition-opacity duration-500 ease-out-strong group-focus-within/cta:[--sun-extend:1] group-hover/cta:[--sun-extend:1] max-lg:left-[calc(72%-220px)] max-lg:h-[169px] max-lg:w-[440px]',
            sunStyles[tone],
          )}
        />

        <p
          className={cn(
            'mb-[18px] font-mono text-[11px] tracking-[0.32em] uppercase',
            fill ? 'text-on-accent/70' : 'text-ink-muted',
          )}
        >
          {eyebrow}
        </p>
        <h3 className="font-serif text-[clamp(38px,4.2vw,56px)] leading-[1.02] tracking-[-0.026em]">
          {/* Stretched link: вся карточка ведёт по основному пути, вторичные ссылки лежат поверх. */}
          <a
            href={href}
            className={cn(
              'after:absolute after:inset-0 after:z-10 after:rounded-2xl focus-visible:outline-none focus-visible:after:outline-1 focus-visible:after:-outline-offset-6',
              fill ? 'after:outline-on-accent' : 'after:outline-accent',
            )}
          >
            {title}
          </a>
        </h3>
        <p className={cn('mt-3 max-w-[32ch] text-base', fill ? 'text-on-accent/80' : 'text-ink-muted')}>{text}</p>

        <ul
          aria-label={extrasLabel}
          className={cn('relative z-20 mt-[22px] flex max-w-[40ch] flex-wrap gap-2', !fill && 'lg:justify-end')}
        >
          {extras.map((extra) => (
            <li key={extra.label}>
              {extra.href ? (
                <a
                  href={extra.href}
                  className="inline-flex h-[30px] items-center rounded-full px-3 font-mono text-[12.5px] inset-ring inset-ring-on-accent/28 transition-[background-color,color,box-shadow] duration-200 hover:bg-on-accent hover:text-accent hover:inset-ring-transparent"
                >
                  {extra.label}
                </a>
              ) : (
                <span className="inline-flex h-[30px] items-center gap-1.5 rounded-full px-3 font-mono text-[12.5px] text-ink-muted inset-ring inset-ring-line-strong before:size-[5px] before:rounded-full before:bg-accent">
                  {extra.label}
                </span>
              )}
            </li>
          ))}
        </ul>

        <span
          className={cn(
            'mt-auto flex items-center gap-3.5 pt-8 font-mono text-[13.5px] font-medium',
            !fill && 'lg:flex-row-reverse',
          )}
        >
          <span
            aria-hidden="true"
            className={cn(
              'grid size-12 place-items-center rounded-full transition-[scale] duration-300 ease-out-strong group-focus-within/cta:scale-[1.06] group-hover/cta:scale-[1.06] group-active/cta:scale-[0.94]',
              fill ? 'bg-on-accent text-accent' : 'bg-accent text-on-accent',
            )}
          >
            <ArrowRightIcon className="size-[18px] -rotate-45 transition-[rotate] duration-300 ease-out-strong group-focus-within/cta:rotate-0 group-hover/cta:rotate-0" />
          </span>
          {action}
        </span>
      </article>
    </Reveal>
  )
}

/** Зенит восхода в зазоре между карточками: кусок дуги, вертикальный луч и точка (R = 155 · 600/640). */
function SunZenith() {
  return (
    <svg
      data-sun-zenith
      viewBox="0 0 16 150"
      fill="none"
      stroke="currentColor"
      aria-hidden="true"
      className="pointer-events-none absolute bottom-0 left-[calc(50%-8px)] h-[150px] w-4 overflow-visible text-accent max-lg:hidden"
    >
      <path strokeWidth="1.5" d="M-1 4.97Q8 4.41 17 4.97" />
      <line x1="8" y1="4.69" x2="8" y2="83.16" strokeWidth="1" />
      <circle cx="8" cy="87.52" r="2.2" fill="currentColor" stroke="none" />
    </svg>
  )
}

const ledger = [
  { label: siteConfig.license },
  { label: 'Built in public' },
  { label: 'Test reports ↗', href: siteConfig.links.evidence },
] as const

export function GetInvolved() {
  const titleId = `${sectionIds.involved}-title`
  const { repo } = siteConfig.links
  return (
    <section id={sectionIds.involved} aria-labelledby={titleId} className="scroll-mt-24 pb-28 max-sm:pb-[72px]">
      <Container>
        <SectionHeading
          id={titleId}
          label="Get involved"
          title={
            <>
              Build it <em>with us.</em>
            </>
          }
        />
        <div ref={mountSunrise} className="group/involved relative grid gap-4 lg:grid-cols-2">
          <ActionCard
            tone="fill"
            eyebrow="For builders"
            href={repo}
            title="Contribute"
            text="File issues, fix bugs, and ship features with us."
            action="Open on GitHub"
            extrasLabel="Other ways to help"
            extras={[
              { label: 'Report a bug', href: `${repo}/issues/new` },
              { label: 'Test on real hardware', href: `${repo}/issues/new` },
              { label: 'Improve the docs', href: siteConfig.links.docs },
            ]}
          />
          <SunZenith />
          <ActionCard
            tone="line"
            eyebrow="For backers"
            href={siteConfig.links.donate}
            title="Donate"
            text="Fund the people and the test hardware behind AGI OS."
            action="Become a patron"
            extrasLabel="Where the money goes"
            extras={[{ label: 'Maintainer time' }, { label: 'Test hardware' }]}
          />
        </div>
        <Reveal>
          <ul className="mt-7 flex flex-wrap items-center justify-center gap-x-[22px] gap-y-2 font-mono text-[11.5px] tracking-[0.2em] text-ink-dim uppercase max-sm:gap-x-3.5">
            {ledger.map((item) => (
              <li
                key={item.label}
                className="flex items-center gap-[22px] not-first:before:size-[3px] not-first:before:rounded-full not-first:before:bg-ink-dim max-sm:gap-3.5"
              >
                {'href' in item ? (
                  <a href={item.href} className="text-ink-muted transition-colors duration-200 hover:text-accent">
                    {item.label}
                  </a>
                ) : (
                  item.label
                )}
              </li>
            ))}
          </ul>
        </Reveal>
      </Container>
    </section>
  )
}
