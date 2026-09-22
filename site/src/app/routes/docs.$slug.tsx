import { createFileRoute, notFound } from '@tanstack/react-router'

import { findDocPage } from '@/entities/doc'
import { DocsPage } from '@/pages/docs'
import { siteConfig } from '@/shared/config'

export const Route = createFileRoute('/docs/$slug')({
  // Страницы — статический реестр, поэтому loader только проверяет slug; контент (React-узлы) не сериализуется.
  loader: ({ params }) => {
    const page = findDocPage(params.slug)
    if (!page) throw notFound()
    return { slug: page.slug, short: page.short, lede: page.lede }
  },
  head: ({ loaderData }) => ({
    meta: loaderData
      ? [
          { title: `${loaderData.short} — ${siteConfig.name} Docs` },
          { name: 'description', content: loaderData.lede },
        ]
      : [],
  }),
  component: DocsSlugRoute,
})

function DocsSlugRoute() {
  const { slug } = Route.useLoaderData()
  const page = findDocPage(slug)
  if (!page) throw notFound()
  return <DocsPage page={page} />
}
