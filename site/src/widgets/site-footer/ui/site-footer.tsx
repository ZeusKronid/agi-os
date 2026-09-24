import { sectionIds, siteConfig } from '@/shared/config'
import { cn } from '@/shared/lib/cn'
import { Container } from '@/shared/ui/container'
import { ArrowRightIcon, ArrowUpIcon } from '@/shared/ui/icon'
import { Sunburst } from '@/shared/ui/sunburst'

import { mountSunset } from '../lib/mount-sunset'

interface FooterLink {
  label: string
  /** Коротко, куда ведёт ссылка. */
  hint: string
  href: string
  external?: boolean
}

// Ссылки сгруппированы по задаче, а не по разделу сайта.
const groups: readonly { title: string; links: readonly FooterLink[] }[] = [
  {
    title: 'Start',
    links: [
      { label: 'Download ISO', hint: 'Live image and checksum', href: siteConfig.links.install },
      { label: 'How it works', hint: 'Listen, preview, build, install', href: `/#${sectionIds.demo}` },
      { label: 'Getting started', hint: 'First boot, in a VM first', href: `${siteConfig.links.docs}/getting-started` },
    ],
  },
  {
    title: 'Learn',
    links: [
      { label: 'Docs', hint: 'How the live environment works', href: siteConfig.links.docs },
      { label: 'FAQ', hint: 'Disks, keys, agents, hardware', href: `/#${sectionIds.faq}` },
      { label: 'Test reports', hint: 'Every run we recorded', href: siteConfig.links.evidence, external: true },
    ],
  },
  {
    title: 'Build with us',
    links: [
      { label: 'GitHub', hint: 'Source, issues, pull requests', href: siteConfig.links.repo, external: true },
      {
        label: 'Report a result',
        hint: 'Tell us how it ran on your machine',
        href: `${siteConfig.links.repo}/issues/new`,
        external: true,
      },
      { label: 'Get involved', hint: 'Contribute or donate', href: `/#${sectionIds.involved}` },
    ],
  },
]

const WORDMARK = ['A', 'G', 'I', 'O', 'S'] as const

// Закат: страница открывается восходом в hero и закрывается здесь. Сверху — ссылки по задачам, под ними
// сцена заката: живой восход на горизонте за огромным wordmark AGIOS, буквы — тёмные силуэты с контуром.
// Пока страница докручивается до конца, солнце садится за буквы (`mountSunset`), клик по солнцу или
// «Back to sunrise» везёт наверх, к восходу.
// Футер — один блок: сверху граница с коралловой точкой на оси страницы, под ней ссылки и сразу сцена.
// Размеры сцены: `--fs` — кегль wordmark (его верх — горизонт, ≈0.66 кегля от низа), `--sun-w` — ширина
// восхода (радиус = 155/640 ширины). Высота сцены = горизонт + 1.2 радиуса (видимая длина лучей), поэтому
// лучи подходят к ссылкам с небольшим ровным зазором на любом экране, без пустоты между ними.
export function SiteFooter() {
  return (
    <footer
      ref={mountSunset}
      className="relative touch-pan-y overflow-hidden [--fs:clamp(96px,23vw,340px)] [--sun-w:min(1100px,76vw)] max-sm:[--sun-w:150vw]"
    >
      {/* Граница сверху: линия на всю ширину и коралловая точка на оси страницы (футер обрезает всё, что выше края,
          поэтому линия чуть ниже края, а точка — по её центру). */}
      <span aria-hidden="true" className="absolute inset-x-0 top-[2px] h-px bg-line-strong" />
      <span aria-hidden="true" className="absolute top-0 left-1/2 size-[5px] -translate-x-1/2 rounded-full bg-accent" />
      <Container className="relative z-20 pt-16 max-sm:pt-12">
        <nav
          aria-label="Footer"
          className="grid grid-cols-3 gap-x-14 gap-y-10 max-lg:grid-cols-2 max-sm:grid-cols-1 max-sm:gap-y-8"
        >
          {groups.map((group) => (
            <div key={group.title}>
              <h2 className="mb-[18px] font-mono text-[11px] tracking-[0.3em] text-ink-dim uppercase">{group.title}</h2>
              <ul className="grid gap-1">
                {group.links.map((link) => (
                  <li key={link.label}>
                    <a
                      href={link.href}
                      className="group/link -mx-3 grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-0.5 rounded-[10px] px-3 py-2.5 transition-colors duration-200 ease-out-strong hover:bg-surface focus-visible:bg-surface"
                    >
                      <span className="font-serif text-[19px] leading-[1.2] text-ink-soft transition-colors duration-200 group-hover/link:text-ink group-focus-visible/link:text-ink">
                        {link.label}
                      </span>
                      <ArrowRightIcon
                        className={cn(
                          'col-start-2 row-span-2 size-[15px] text-ink-dim transition-[rotate,translate,color] duration-300 ease-out-strong group-hover/link:text-accent group-focus-visible/link:text-accent',
                          link.external
                            ? '-rotate-45 group-hover/link:translate-x-0.5 group-hover/link:-translate-y-0.5'
                            : 'group-hover/link:translate-x-[3px]',
                        )}
                      />
                      <span className="font-mono text-xs leading-[1.4] text-ink-dim">{link.hint}</span>
                      {link.external && <span className="sr-only"> (opens GitHub)</span>}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <p className="mt-10 flex justify-between gap-5 font-mono text-[11.5px] tracking-[0.08em] text-ink-dim max-sm:mt-8 max-sm:flex-col max-sm:gap-1.5">
          <span>
            © 2026 {siteConfig.name} · {siteConfig.license} License
          </span>
          <span>Built in public</span>
        </p>
      </Container>

      <div className="relative h-[calc(var(--fs)*0.66_+_var(--sun-w)*155/640*1.2)]">
        <div className="pointer-events-none absolute inset-x-0 bottom-[calc(var(--fs)*0.66)] flex justify-center">
          <Sunburst variant="live" className="w-(--sun-w) shrink-0 overflow-visible text-accent" />
        </div>

        {/* Клик по солнцу — туда же, куда «Back to sunrise»: это дубль для мыши, с клавиатуры — ссылка ниже. */}
        <a
          href={`#${sectionIds.top}`}
          tabIndex={-1}
          aria-hidden="true"
          className="absolute bottom-[calc(var(--fs)*0.66)] left-1/2 z-10 h-[calc(var(--sun-w)*155/640)] w-[calc(var(--sun-w)*310/640)] -translate-x-1/2 cursor-pointer rounded-t-full"
        />
        <a
          href={`#${sectionIds.top}`}
          className="group/rise absolute bottom-[calc(var(--fs)*0.66_+_var(--sun-w)*155/640*0.3)] left-1/2 z-30 flex -translate-x-1/2 items-center gap-2 rounded-full bg-canvas/95 px-4 py-2.5 font-mono text-[11px] tracking-[0.26em] whitespace-nowrap text-ink-muted uppercase inset-ring inset-ring-line transition-[color,scale,box-shadow] duration-200 hover:text-ink hover:inset-ring-line-accent active:scale-[0.96]"
        >
          <ArrowUpIcon className="size-3.5 transition-[translate] duration-300 ease-out-strong group-hover/rise:-translate-y-0.5" />
          Back to sunrise
        </a>

        {/* Декоративный wordmark: единственное место логотипного шрифта. Буквы — силуэты: солнце садится за них. */}
        <p
          aria-hidden="true"
          className="absolute inset-x-0 bottom-0 z-20 flex justify-center overflow-hidden select-none"
        >
          {WORDMARK.map((letter) => (
            <span
              key={letter}
              className="-mb-[0.1em] block font-logo text-(length:--fs) leading-[0.78] font-bold tracking-[-0.02em] text-canvas transition-[translate,-webkit-text-stroke-color] duration-[450ms] ease-out-strong [-webkit-text-stroke:1px_rgb(255_255_255/0.18)] hover:-translate-y-[0.05em] hover:[-webkit-text-stroke-color:var(--color-accent)]"
            >
              {letter}
            </span>
          ))}
        </p>
      </div>
    </footer>
  )
}
