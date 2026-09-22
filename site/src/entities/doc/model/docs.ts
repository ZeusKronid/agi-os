import { providers } from './pages/agents'
import { agentAndPrivacy, liveEnvironment, reversiblePreview } from './pages/concepts'
import { gettingStarted } from './pages/getting-started'
import { contribute, faq } from './pages/more'
import { disksAndBoot, previewPlacement } from './pages/storage'
import type { DocChapter, DocChapterId, DocPage } from './types'

export const docChapters: readonly DocChapter[] = [
  { id: 'start', label: 'Getting Started' },
  { id: 'concepts', label: 'Concepts' },
  { id: 'agents', label: 'Agents' },
  { id: 'storage', label: 'Storage' },
  { id: 'more', label: 'FAQ & more' },
]

/** Порядок = порядок чтения и карточек «Previous / Next». */
export const docPages: readonly DocPage[] = [
  gettingStarted,
  liveEnvironment,
  reversiblePreview,
  agentAndPrivacy,
  providers,
  previewPlacement,
  disksAndBoot,
  faq,
  contribute,
]

/** Страница, которая открывается на `/docs` без сегмента. */
export const docIndexPage: DocPage = gettingStarted

export function findDocPage(slug: string): DocPage | undefined {
  return docPages.find((page) => page.slug === slug)
}

export function docPagesOf(chapter: DocChapterId): readonly DocPage[] {
  return docPages.filter((page) => page.chapter === chapter)
}

export function adjacentDocPages(page: DocPage): { prev?: DocPage; next?: DocPage } {
  const index = docPages.indexOf(page)
  return { prev: docPages[index - 1], next: docPages[index + 1] }
}

export function docChapterOf(page: DocPage): DocChapter {
  const chapter = docChapters.find((item) => item.id === page.chapter)
  if (!chapter) throw new Error(`Unknown docs chapter: ${page.chapter}`)
  return chapter
}
