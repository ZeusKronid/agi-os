import { createFileRoute } from '@tanstack/react-router'

import { docIndexPage, docPages } from '@/entities/doc'
import { absoluteUrl } from '@/shared/lib/seo'

// Только канонические адреса: обзор документации живёт на `/docs`, его slug-адрес — редирект.
const paths = [
  '/',
  '/install',
  '/docs',
  ...docPages.filter((page) => page.slug !== docIndexPage.slug).map((page) => `/docs/${page.slug}`),
]

function sitemapXml(): string {
  const urls = paths.map((path) => `  <url><loc>${absoluteUrl(path)}</loc></url>`).join('\n')
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`
}

export const Route = createFileRoute('/sitemap.xml')({
  server: {
    handlers: {
      GET: () =>
        new Response(sitemapXml(), {
          headers: { 'content-type': 'application/xml; charset=utf-8', 'cache-control': 'public, max-age=3600' },
        }),
    },
  },
})
