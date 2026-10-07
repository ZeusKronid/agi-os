export const sectionIds = {
  main: 'main',
  top: 'top',
  demo: 'how',
  features: 'features',
  faq: 'faq',
  involved: 'involved',
} as const

const repo = 'https://github.com/ZeusKronid/agi-os'

export const siteConfig = {
  name: 'AGI OS',
  /** Канонический origin: из него строятся canonical, og:url, sitemap и JSON-LD. */
  url: 'https://agios.complexity.solutions',
  title: 'AGI OS — Agentic Linux: Describe It, Try It Live, Install',
  description:
    'AGI OS is an Arch Linux live ISO with an AI agent inside. Describe the system you want in plain words, try it in a live preview, then install it.',
  /** Картинка превью для соцсетей и мессенджеров, 1200×630. */
  ogImage: { path: '/og.png', width: 1200, height: 630, alt: 'AGI OS — Modern agentic Linux' },
  themeColor: '#0b0908',
  license: 'Apache-2.0',
  links: {
    repo,
    docs: '/docs',
    install: '/install',
    // Страница релиза с ISO, контрольной суммой и заметками.
    download: `${repo}/releases/latest`,
    // Статус приёмочных прогонов; сами отчёты в репозиторий не коммитятся.
    evidence: `${repo}/blob/HEAD/docs/installation-testing.md`,
    // TODO: заменить на реальную страницу пожертвований, когда она появится.
    donate: repo,
  },
  /** Umami на своём сервере: без cookie, IP не хранится. ID сайта публичный — он всё равно виден в HTML. */
  analytics: {
    scriptUrl: 'https://agios-stats.2.29.47.11.sslip.io/insights.js',
    websiteId: '19629fec-efb3-4efc-9ced-b2054be9ea84',
  },
  nav: [
    { label: 'Features', href: `/#${sectionIds.features}` },
    { label: 'Get Involved', href: `/#${sectionIds.involved}` },
    // Отдельная страница, а не якорь: шапка рендерит её через router `Link`.
    { label: 'Docs', to: '/docs' },
  ],
} as const
