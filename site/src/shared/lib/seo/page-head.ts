import { siteConfig } from '@/shared/config'

/** Узел schema.org для `<script type="application/ld+json">`. */
export type JsonLd = Record<string, unknown>

interface PageHeadOptions {
  title: string
  description: string
  /** Путь от корня сайта (`/install`); из него строятся canonical и og:url. */
  path: string
  type?: 'website' | 'article'
  jsonLd?: readonly JsonLd[]
}

export function absoluteUrl(path: string): string {
  return new URL(path, siteConfig.url).href
}

/**
 * Мета одной страницы: title, description, canonical, Open Graph, Twitter и JSON-LD.
 * Вызывать только в листовых маршрутах: `links` из всех совпавших маршрутов складываются,
 * поэтому canonical в корне продублировался бы на каждой странице. Мета с тем же `name` или
 * `property` у листа перекрывает корневую.
 */
export function pageHead({ title, description, path, type = 'website', jsonLd = [] }: PageHeadOptions) {
  const url = absoluteUrl(path)
  return {
    meta: [
      { title },
      { name: 'description', content: description },
      { property: 'og:type', content: type },
      { property: 'og:url', content: url },
      { property: 'og:title', content: title },
      { property: 'og:description', content: description },
      { name: 'twitter:title', content: title },
      { name: 'twitter:description', content: description },
    ],
    links: [{ rel: 'canonical', href: url }],
    // Через `scripts`, а не `script:ld+json` в meta: в типах React Router meta — только атрибуты `<meta>`.
    // `<` экранируется, чтобы строка в данных не могла закрыть тег скрипта.
    scripts: jsonLd.map((node) => ({
      type: 'application/ld+json',
      children: JSON.stringify(node).replace(/</g, '\\u003c'),
    })),
  }
}

/** Издатель и сайт: на них ссылаются остальные узлы через `@id`. */
export const organizationId = absoluteUrl('/#organization')
export const websiteId = absoluteUrl('/#website')

export const organizationLd: JsonLd = {
  '@context': 'https://schema.org',
  '@type': 'Organization',
  '@id': organizationId,
  name: siteConfig.name,
  url: absoluteUrl('/'),
  logo: absoluteUrl('/icon-512.png'),
  sameAs: [siteConfig.links.repo],
}

export const websiteLd: JsonLd = {
  '@context': 'https://schema.org',
  '@type': 'WebSite',
  '@id': websiteId,
  name: siteConfig.name,
  alternateName: 'AGIOS',
  url: absoluteUrl('/'),
  inLanguage: 'en',
  publisher: { '@id': organizationId },
}

export function breadcrumbLd(items: readonly { name: string; path: string }[]): JsonLd {
  return {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: items.map((item, index) => ({
      '@type': 'ListItem',
      position: index + 1,
      name: item.name,
      item: absoluteUrl(item.path),
    })),
  }
}
