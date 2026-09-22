import { createFileRoute } from '@tanstack/react-router'

import { docIndexPage } from '@/entities/doc'
import { DocsPage } from '@/pages/docs'
import { siteConfig } from '@/shared/config'

export const Route = createFileRoute('/docs/')({
  head: () => ({
    meta: [
      { title: `${docIndexPage.short} — ${siteConfig.name} Docs` },
      { name: 'description', content: docIndexPage.lede },
    ],
  }),
  component: DocsIndexRoute,
})

function DocsIndexRoute() {
  return <DocsPage page={docIndexPage} />
}
