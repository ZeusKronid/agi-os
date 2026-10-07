import { siteConfig } from '@/shared/config'
import { absoluteUrl, breadcrumbLd, organizationId, pageHead } from '@/shared/lib/seo'

import type { DocPage } from '../model/types'

/** Сериализуемая часть страницы, которую loader отдаёт в `head()`: React-узлы секций не сериализуются. */
export interface DocHeadData {
  path: string
  short: string
  metaTitle: string
  description: string
}

export function docHeadData(page: DocPage, path: string): DocHeadData {
  return { path, short: page.short, metaTitle: page.metaTitle, description: page.metaDescription ?? page.lede }
}

export function docHead(data: DocHeadData) {
  return pageHead({
    title: data.metaTitle,
    description: data.description,
    path: data.path,
    type: 'article',
    jsonLd: [
      {
        '@context': 'https://schema.org',
        '@type': 'TechArticle',
        headline: data.metaTitle,
        description: data.description,
        url: absoluteUrl(data.path),
        inLanguage: 'en',
        image: absoluteUrl(siteConfig.ogImage.path),
        about: { '@type': 'SoftwareApplication', name: siteConfig.name },
        author: { '@id': organizationId },
        publisher: { '@id': organizationId },
      },
      breadcrumbLd([
        { name: siteConfig.name, path: '/' },
        { name: 'Docs', path: '/docs' },
        ...(data.path === '/docs' ? [] : [{ name: data.short, path: data.path }]),
      ]),
    ],
  })
}
