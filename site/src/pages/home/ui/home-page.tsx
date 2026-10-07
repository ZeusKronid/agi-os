import { useEffect } from 'react'

import { sectionIds } from '@/shared/config'
import { trackSectionViews } from '@/shared/lib/analytics'
import { AgentsMarquee } from '@/widgets/agents-marquee'
import { Faq } from '@/widgets/faq'
import { FeatureGrid } from '@/widgets/feature-grid'
import { GetInvolved } from '@/widgets/get-involved'
import { Hero } from '@/widgets/hero'

export function HomePage() {
  // Докуда дочитывают главную: каждая секция — одно событие за визит.
  useEffect(() => trackSectionViews([sectionIds.demo, sectionIds.features, sectionIds.faq, sectionIds.involved]), [])

  return (
    <>
      <Hero />
      <AgentsMarquee />
      <FeatureGrid />
      <Faq />
      <GetInvolved />
    </>
  )
}
