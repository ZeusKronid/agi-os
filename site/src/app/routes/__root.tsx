import { createRootRoute, Outlet } from '@tanstack/react-router'

import { siteConfig } from '@/shared/config'
import { absoluteUrl } from '@/shared/lib/seo'

import { RootDocument } from '../layouts/root-document'
import geistLatin from '../styles/fonts/geist-latin.woff2?url'
import newsreaderLatin from '../styles/fonts/newsreader-latin.woff2?url'
import appCss from '../styles/index.css?url'

const ogImage = absoluteUrl(siteConfig.ogImage.path)

export const Route = createRootRoute({
  // Общая мета и запасные значения для страниц без своей (404). Canonical, og:url и JSON-LD задают
  // листовые маршруты через `pageHead`: ссылки из всех маршрутов складываются, а мета листа перекрывает корневую.
  head: ({ matches }) => {
    // 404: страница не должна попасть в индекс, а мета главной на ней вводила бы поиск в заблуждение.
    // Неизвестный путь совпадает только с корнем; известный, но без страницы (`/docs/<нет>`) — notFound из loader.
    const notFound = matches.length === 1 || matches.some((match) => match.status === 'notFound')
    return {
      meta: [
        { charSet: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'theme-color', content: siteConfig.themeColor },
        ...(notFound
          ? [{ title: `Page not found — ${siteConfig.name}` }, { name: 'robots', content: 'noindex' }]
          : [{ title: siteConfig.title }, { name: 'description', content: siteConfig.description }]),
        { property: 'og:site_name', content: siteConfig.name },
        { property: 'og:locale', content: 'en_US' },
        { property: 'og:image', content: ogImage },
        { property: 'og:image:width', content: String(siteConfig.ogImage.width) },
        { property: 'og:image:height', content: String(siteConfig.ogImage.height) },
        { property: 'og:image:alt', content: siteConfig.ogImage.alt },
        { name: 'twitter:card', content: 'summary_large_image' },
        { name: 'twitter:image', content: ogImage },
      ],
      links: [
        // Шрифты первого экрана: H1 героя (Newsreader) и основной текст (Geist). Остальные подтянет CSS.
        { rel: 'preload', href: newsreaderLatin, as: 'font', type: 'font/woff2', crossOrigin: 'anonymous' },
        { rel: 'preload', href: geistLatin, as: 'font', type: 'font/woff2', crossOrigin: 'anonymous' },
        { rel: 'stylesheet', href: appCss },
        { rel: 'icon', href: '/favicon.ico', sizes: '32x32' },
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
        { rel: 'apple-touch-icon', href: '/apple-touch-icon.png' },
        { rel: 'manifest', href: '/site.webmanifest' },
      ],
    }
  },
  component: RootComponent,
})

function RootComponent() {
  return (
    <RootDocument>
      <Outlet />
    </RootDocument>
  )
}
