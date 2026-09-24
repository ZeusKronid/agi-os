import type { ReactNode } from 'react'

export type DocChapterId = 'start' | 'concepts' | 'agents' | 'storage' | 'more'

export interface DocChapter {
  id: DocChapterId
  label: string
}

export interface DocSection {
  /** Якорь внутри страницы (`#boot`). Уникален в пределах страницы. */
  id: string
  title: string
  /** Короткий текст для поискового индекса: содержимое секций — React-узлы, их не проиндексировать. */
  summary: string
  content: ReactNode
}

export interface DocPage {
  /** Сегмент URL: `/docs/<slug>`. Страница `getting-started` живёт на `/docs`. */
  slug: string
  chapter: DocChapterId
  /** Название в дереве и в карточках «Previous / Next». */
  short: string
  /** Заголовок страницы; одно слово выделяется курсивом и кораллом через `em`. */
  title: string
  em: string
  lede: string
  sections: readonly DocSection[]
}
