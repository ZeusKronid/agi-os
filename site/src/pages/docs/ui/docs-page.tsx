import { useCallback, useMemo, useState } from 'react'

import { adjacentDocPages, docChapterOf, DocLink, Prose, type DocPage as DocPageModel } from '@/entities/doc'
import { DocsSearchButton, DocsSearchPalette } from '@/features/docs-search'
import { useActiveSection } from '@/shared/lib/scroll-spy'
import { Container } from '@/shared/ui/container'
import { DocsDrawer, DocsTree } from '@/widgets/docs-sidebar'
import { DocsToc, DocsTocCompact } from '@/widgets/docs-toc'

interface DocsPageProps {
  page: DocPageModel
}

/**
 * Документация в три колонки: дерево слева, статья по центру (66 символов), «On this page» справа.
 * Ниже `lg` правая колонка сворачивается в компактное оглавление под заголовком,
 * ниже `md` дерево уезжает в drawer, а над статьёй появляется панель «Search · Docs menu».
 */
export function DocsPage({ page }: DocsPageProps) {
  const [searchOpen, setSearchOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const sectionIds = useMemo(() => page.sections.map((section) => section.id), [page])
  const activeSection = useActiveSection(sectionIds)
  const openSearch = useCallback(() => setSearchOpen(true), [])
  const closeSearch = useCallback(() => setSearchOpen(false), [])
  const closeDrawer = useCallback(() => setDrawerOpen(false), [])
  const chapter = docChapterOf(page)
  const { prev, next } = adjacentDocPages(page)

  return (
    <Container className="grid gap-x-10 gap-y-0 pt-3 pb-[72px] md:grid-cols-[230px_minmax(0,1fr)] md:pt-7 md:pb-24 lg:grid-cols-[250px_minmax(0,1fr)_210px] lg:gap-x-14">
      <aside className="sticky top-[104px] self-start max-md:hidden">
        <DocsSearchButton onClick={openSearch} />
        <div className="mt-[22px]">
          <DocsTree key={page.slug} current={page} activeSection={activeSection} />
        </div>
      </aside>

      <article className="min-w-0">
        <div className="mb-[18px] flex items-center gap-2.5 md:hidden">
          <DocsSearchButton compact onClick={openSearch} />
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            className="h-[38px] shrink-0 rounded-lg px-3.5 font-serif text-[15px] text-ink-soft inset-ring inset-ring-line-accent transition-[box-shadow] duration-200 hover:inset-ring-accent"
          >
            Docs menu
          </button>
        </div>

        <p className="flex items-center gap-2.5 font-mono text-[11px] tracking-[0.2em] text-ink-muted uppercase">
          <span>Docs</span>
          <span aria-hidden="true" className="size-[5px] rounded-full bg-accent" />
          <span>{chapter.label}</span>
        </p>
        <h1 className="mt-[18px] font-serif text-[clamp(36px,4.2vw,56px)] leading-[1.04] tracking-[-0.024em] text-balance">
          {page.title} <em className="text-accent">{page.em}</em>
        </h1>
        <p className="mt-[18px] max-w-[60ch] text-lg leading-[1.55] text-ink-muted">{page.lede}</p>

        <div className="mt-[26px]">
          <DocsTocCompact page={page} />
        </div>

        <div className="mt-10 grid gap-12">
          {page.sections.map((section) => (
            <section key={section.id} aria-labelledby={`${section.id}-title`}>
              <h2
                id={section.id}
                className="mb-[18px] scroll-mt-28 font-serif text-[30px] leading-[1.12] tracking-[-0.02em] text-balance"
              >
                <span id={`${section.id}-title`}>{section.title}</span>
              </h2>
              <Prose>{section.content}</Prose>
            </section>
          ))}
        </div>

        <nav aria-label="Pages" className="mt-16 grid max-w-[66ch] gap-4 sm:grid-cols-2">
          {prev ? <PagerLink page={prev} direction="prev" /> : <span />}
          {next && <PagerLink page={next} direction="next" />}
        </nav>
      </article>

      <div className="max-lg:hidden">
        <DocsToc page={page} activeSection={activeSection} />
      </div>

      <DocsSearchPalette open={searchOpen} onOpen={openSearch} onClose={closeSearch} />
      <DocsDrawer key={page.slug} open={drawerOpen} onClose={closeDrawer} current={page} activeSection={activeSection} />
    </Container>
  )
}

interface PagerLinkProps {
  page: DocPageModel
  direction: 'prev' | 'next'
}

function PagerLink({ page, direction }: PagerLinkProps) {
  const isNext = direction === 'next'
  return (
    <DocLink
      page={page}
      rel={direction}
      className="group grid gap-1 rounded-xl bg-surface px-[18px] py-4 inset-ring inset-ring-line transition-[box-shadow,translate] duration-250 ease-out-strong hover:-translate-y-0.5 hover:inset-ring-line-accent data-[dir=next]:text-right"
      data-dir={direction}
    >
      <span className="font-mono text-[10.5px] tracking-[0.2em] text-ink-muted uppercase">
        {isNext ? 'Next →' : '← Previous'}
      </span>
      <span className="font-serif text-[19px] text-ink">{page.short}</span>
    </DocLink>
  )
}
