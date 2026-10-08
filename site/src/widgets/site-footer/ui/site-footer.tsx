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
      { label: 'Getting started', hint: 'First boot, in a VM first', href: siteConfig.links.docs },
    ],
  },
  {
    title: 'Learn',
    links: [
      { label: 'Docs', hint: 'How the live environment works', href: `${siteConfig.links.docs}/live-environment` },
      { label: 'FAQ', hint: 'Disks, keys, agents, hardware', href: `/#${sectionIds.faq}` },
      { label: 'Test status', hint: 'What passed in VM runs', href: siteConfig.links.evidence, external: true },
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

// Wordmark AGIOS — знак из шапки (`shared/ui/logo`), линии которого обведены в контуры (толщина 34, квадратные
// концы, острые стыки): у букв есть заливка Canvas и тонкий контур, как у силуэтов. Внутренние контуры A и O — дыры
// (evenodd), сквозь них видно солнце.
const WORDMARK = [
  { letter: 'A', d: 'M62.5 292 L307.5 292 L185 47 Z M117.5 258 L185 123 L252.5 258 Z' },
  {
    letter: 'G',
    d: 'M299.7 179.3 L487 313 L487 173 L398 173 L398 207 L453 207 L453 247 L360.3 180.7 L493.5 95.1 L475.1 66.5 Z',
  },
  { letter: 'I', d: 'M548 73 L548 292 L582 292 L582 73 Z' },
  { letter: 'O', d: 'M760 61 L641 180 L760 299 L879 180 Z M760 109 L831 180 L760 251 L689 180 Z' },
  {
    letter: 'S',
    d: 'M905.1 155.3 L1035.8 215.6 L922.2 272.4 L937.4 302.8 L1114.2 214.4 L984.9 154.7 L1102.7 97.9 L1087.9 67.3 Z',
  },
] as const

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
              <p className="mb-[18px] font-mono text-[11px] tracking-[0.3em] text-ink-dim uppercase">{group.title}</p>
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

        {/* Декоративный wordmark: буквы — силуэты, солнце садится за них. Верх A (y 47) — горизонт, 0.66 кегля над
            низом сцены (240 единиц viewBox = 0.66 кегля); сверху запас 22 единицы под подъём на hover (0.05 кегля
            ≈ 18 единиц), снизу viewBox обрезает буквы, как раньше нижний край обрезал шрифт. */}
        <svg
          aria-hidden="true"
          viewBox="60 25 1057 260"
          className="absolute bottom-0 left-1/2 z-20 h-[calc(var(--fs)*0.715)] -translate-x-1/2 select-none"
        >
          {WORDMARK.map(({ letter, d }) => (
            <path
              key={letter}
              d={d}
              fillRule="evenodd"
              vectorEffect="non-scaling-stroke"
              className="fill-canvas stroke-white/18 stroke-1 transition-[translate,stroke] duration-[450ms] ease-out-strong hover:stroke-accent hover:[translate:0_-18px]"
            />
          ))}
        </svg>
      </div>
    </footer>
  )
}
