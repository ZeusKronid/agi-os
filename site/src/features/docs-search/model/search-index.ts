import { docPages, type DocPage, type DocSection } from '@/entities/doc'

export interface SearchHit {
  page: DocPage
  section: DocSection
}

interface IndexEntry extends SearchHit {
  text: string
}

const MAX_HITS = 7

// Индекс строится один раз на модуль: заголовок секции + краткое содержание + название страницы.
const index: readonly IndexEntry[] = docPages.flatMap((page) =>
  page.sections.map((section) => ({
    page,
    section,
    text: `${section.title} ${section.summary} ${page.short}`.toLowerCase(),
  })),
)

/** Пустой запрос показывает первые секции обзора — подсказка, с чего начать. */
export function searchDocs(query: string): SearchHit[] {
  const q = query.trim().toLowerCase()
  const entries = q ? index.filter((entry) => entry.text.includes(q)) : index
  return entries.slice(0, MAX_HITS).map(({ page, section }) => ({ page, section }))
}
