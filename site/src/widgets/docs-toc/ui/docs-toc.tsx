import type { DocPage } from '@/entities/doc'
import { siteConfig } from '@/shared/config'
import { cn } from '@/shared/lib/cn'
import { ChevronDownIcon } from '@/shared/ui/icon'

interface DocsTocProps {
  page: DocPage
  activeSection: string | null
}

/** «On this page»: липкая колонка справа, активная секция отмечена коралловой линией. */
export function DocsToc({ page, activeSection }: DocsTocProps) {
  return (
    <aside aria-label="On this page" className="sticky top-[104px] self-start">
      <p className="font-mono text-[10.5px] tracking-[0.28em] text-ink-muted uppercase">On this page</p>
      <ul className="mt-3.5 grid gap-0.5 border-l border-line">
        {page.sections.map((section) => (
          <li key={section.id}>
            <a
              href={`#${section.id}`}
              aria-current={activeSection === section.id ? 'true' : undefined}
              className={cn(
                '-ml-px block border-l border-transparent py-[5px] pl-3.5 text-[13.5px] text-ink-muted transition-colors duration-200 hover:text-ink',
                activeSection === section.id && 'border-accent text-ink',
              )}
            >
              {section.title}
            </a>
          </li>
        ))}
      </ul>
      <div className="mt-[22px] grid gap-1.5 border-t border-line pt-4 font-mono text-[11px] text-ink-dim">
        <a href={siteConfig.links.repo} className="text-ink-muted transition-colors duration-200 hover:text-ink">
          Source on GitHub
        </a>
        <span>{siteConfig.license} · x86_64</span>
      </div>
    </aside>
  )
}

/** Компактное оглавление под заголовком на узких экранах (вместо правой колонки). */
export function DocsTocCompact({ page }: Pick<DocsTocProps, 'page'>) {
  return (
    <details className="group rounded-[10px] bg-surface inset-ring inset-ring-line lg:hidden">
      <summary className="flex cursor-pointer list-none items-center justify-between px-3.5 py-3 font-mono text-[10.5px] tracking-[0.28em] text-ink-muted uppercase [&::-webkit-details-marker]:hidden">
        On this page
        <ChevronDownIcon className="size-3 text-ink-dim transition-[rotate] duration-250 ease-out-strong group-open:rotate-180 group-open:text-accent" />
      </summary>
      <ul className="grid gap-1 px-3.5 pb-3">
        {page.sections.map((section) => (
          <li key={section.id}>
            <a href={`#${section.id}`} className="block py-1 text-[14px] text-ink-soft">
              {section.title}
            </a>
          </li>
        ))}
      </ul>
    </details>
  )
}
