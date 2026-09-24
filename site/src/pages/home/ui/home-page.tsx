import { AgentsMarquee } from '@/widgets/agents-marquee'
import { Faq } from '@/widgets/faq'
import { FeatureGrid } from '@/widgets/feature-grid'
import { GetInvolved } from '@/widgets/get-involved'
import { Hero } from '@/widgets/hero'

export function HomePage() {
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
