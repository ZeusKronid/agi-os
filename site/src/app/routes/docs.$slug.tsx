import { createFileRoute, notFound, redirect } from '@tanstack/react-router'

import { docHead, findDocPage } from '@/entities/doc'
import { DocsPage } from '@/pages/docs'

export const Route = createFileRoute('/docs/$slug')({
  // Страницы — статический реестр, поэтому loader только проверяет slug; контент (React-узлы) не сериализуется.
  // Реестр грузится динамически: loader и head не уходят в отдельный чанк, и статический импорт
  // затащил бы тексты всей документации в entry-чанк каждой страницы сайта.
  loader: async ({ params }) => {
    const { docHeadData, docIndexPage, findDocPage } = await import('@/entities/doc')
    // Обзор живёт на `/docs`; его второй адрес — постоянный редирект, чтобы не было дубля в поиске.
    if (params.slug === docIndexPage.slug) throw redirect({ to: '/docs', statusCode: 301 })
    const page = findDocPage(params.slug)
    if (!page) throw notFound()
    return { slug: page.slug, ...docHeadData(page, `/docs/${page.slug}`) }
  },
  head: ({ loaderData }) => (loaderData ? docHead(loaderData) : {}),
  component: DocsSlugRoute,
})

function DocsSlugRoute() {
  const { slug } = Route.useLoaderData()
  const page = findDocPage(slug)
  if (!page) throw notFound()
  return <DocsPage page={page} />
}
