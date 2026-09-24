import { createFileRoute } from '@tanstack/react-router'

import { docIndexPage } from '@/entities/doc'
import { DocsPage } from '@/pages/docs'
import { siteConfig } from '@/shared/config'

export const Route = createFileRoute('/docs/')({
  // Как в `docs.$slug`: реестр грузится динамически, чтобы тексты документации не попали в entry-чанк.
  loader: async () => {
    const { docIndexPage } = await import('@/entities/doc')
    return { short: docIndexPage.short, lede: docIndexPage.lede }
  },
  head: ({ loaderData }) => ({
    meta: loaderData
      ? [
          { title: `${loaderData.short} — ${siteConfig.name} Docs` },
          { name: 'description', content: loaderData.lede },
        ]
      : [],
  }),
  component: DocsIndexRoute,
})

function DocsIndexRoute() {
  return <DocsPage page={docIndexPage} />
}
