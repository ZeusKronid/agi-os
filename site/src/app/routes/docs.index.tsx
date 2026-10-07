import { createFileRoute } from '@tanstack/react-router'

import { docHead, docIndexPage } from '@/entities/doc'
import { DocsPage } from '@/pages/docs'

export const Route = createFileRoute('/docs/')({
  // Как в `docs.$slug`: реестр грузится динамически, чтобы тексты документации не попали в entry-чанк.
  loader: async () => {
    const { docHeadData, docIndexPage } = await import('@/entities/doc')
    return docHeadData(docIndexPage, '/docs')
  },
  head: ({ loaderData }) => (loaderData ? docHead(loaderData) : {}),
  component: DocsIndexRoute,
})

function DocsIndexRoute() {
  return <DocsPage page={docIndexPage} />
}
