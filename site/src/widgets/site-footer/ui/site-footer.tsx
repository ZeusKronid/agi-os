import { sectionIds, siteConfig } from '@/shared/config'
import { Container } from '@/shared/ui/container'

const groups = [
  {
    title: 'Project',
    links: [
      { label: 'Features', href: `/#${sectionIds.features}` },
      { label: 'FAQ', href: `/#${sectionIds.faq}` },
      { label: 'Docs', href: siteConfig.links.docs },
    ],
  },
  {
    title: 'Product',
    links: [
      { label: 'Download ISO', href: siteConfig.links.install },
      { label: 'How it works', href: `/#${sectionIds.demo}` },
      { label: 'Evidence', href: siteConfig.links.evidence },
    ],
  },
  {
    title: 'Community',
    links: [
      { label: 'GitHub', href: siteConfig.links.repo },
      { label: 'Get involved', href: `/#${sectionIds.involved}` },
    ],
  },
] as const

const meta = 'font-mono text-[11px] tracking-[0.24em] uppercase'

// Statement-футер: единственная светлая поверхность сайта. Компактный ряд ссылок, «Back to top»,
// юридическая строка и огромный обрезанный wordmark, прижатый к нижнему краю.
export function SiteFooter() {
  return (
    <footer className="overflow-hidden bg-cream pt-16 text-cream-ink">
      <Container>
        <div className="flex flex-wrap justify-between gap-10">
          <nav aria-label="Footer" className="flex flex-wrap gap-x-16 gap-y-8 max-sm:gap-x-8">
            {groups.map((group) => (
              <ul key={group.title} className="grid content-start gap-2.5">
                <li className={`${meta} mb-2 text-cream-muted`}>{group.title}</li>
                {group.links.map((link) => (
                  <li key={link.label}>
                    <a href={link.href} className="underline-offset-4 hover:underline">
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            ))}
          </nav>
          <a href={`#${sectionIds.top}`} className={`${meta} self-start underline-offset-4 hover:underline`}>
            Back to top ↑
          </a>
        </div>
        <p className="mt-[72px] font-mono text-xs tracking-[0.08em] text-cream-muted">
          © 2026 {siteConfig.name} · {siteConfig.license} License
        </p>
        {/* Декоративный wordmark: единственное место, где используется логотипный шрифт. */}
        <p
          aria-hidden="true"
          className="mt-2 -mb-[0.08em] translate-y-[0.06em] font-logo text-[clamp(96px,23vw,340px)] leading-[0.78] font-bold tracking-[-0.02em] whitespace-nowrap select-none"
        >
          AGIOS
        </p>
      </Container>
    </footer>
  )
}
