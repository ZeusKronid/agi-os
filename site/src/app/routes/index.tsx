import { createFileRoute } from '@tanstack/react-router'

import { release } from '@/entities/release'
import { HomePage } from '@/pages/home'
import { siteConfig } from '@/shared/config'
import { absoluteUrl, organizationId, organizationLd, pageHead, websiteLd } from '@/shared/lib/seo'
import { faqColumns } from '@/widgets/faq'

const softwareLd = {
  '@context': 'https://schema.org',
  '@type': 'SoftwareApplication',
  name: siteConfig.name,
  description: siteConfig.description,
  url: absoluteUrl('/'),
  image: absoluteUrl(siteConfig.ogImage.path),
  applicationCategory: 'UtilitiesApplication',
  applicationSubCategory: 'Linux distribution',
  operatingSystem: 'Linux (x86_64)',
  ...(release.version ? { softwareVersion: release.version } : {}),
  downloadUrl: release.isoUrl,
  license: 'https://www.apache.org/licenses/LICENSE-2.0',
  isAccessibleForFree: true,
  offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
  publisher: { '@id': organizationId },
  sameAs: [siteConfig.links.repo],
}

// Те же вопросы и ответы, что видны в секции FAQ на странице: разметка не должна расходиться с текстом.
const faqLd = {
  '@context': 'https://schema.org',
  '@type': 'FAQPage',
  mainEntity: faqColumns.flat().map((item) => ({
    '@type': 'Question',
    name: item.question,
    acceptedAnswer: { '@type': 'Answer', text: item.answer },
  })),
}

export const Route = createFileRoute('/')({
  head: () =>
    pageHead({
      title: siteConfig.title,
      description: siteConfig.description,
      path: '/',
      jsonLd: [organizationLd, websiteLd, softwareLd, faqLd],
    }),
  component: HomePage,
})
