import type { ReactNode } from 'react'

import { sectionIds } from '@/shared/config'
import { cn } from '@/shared/lib/cn'
import { Container } from '@/shared/ui/container'
import { Reveal } from '@/shared/ui/reveal'
import { SectionHeading } from '@/shared/ui/section-heading'

import { AgentsSignalVisual } from './agents-signal'
import { AtlasVisual } from './atlas-visual'
import { LiveVisual } from './live-visual'
import { SameSystemVisual } from './same-system-visual'
import { WordsVisual } from './words-visual'

interface FeatureCardProps {
  title: string
  text: string
  /** Ширина в сетке из шести колонок: 2 (узкая), 4 (широкая) или 6 (во всю ширину). */
  span?: 2 | 4 | 6
  /** Дополнительные классы области визуала, например другая высота. */
  visualClassName?: string
  children: ReactNode
}

const spans = { 2: 'lg:col-span-2', 4: 'lg:col-span-4', 6: 'lg:col-span-6' } as const

function FeatureCard({ title, text, span = 2, visualClassName, children }: FeatureCardProps) {
  return (
    // Reveal трансформирует внешний узел через GSAP, поэтому hover-сдвиг живёт на внутреннем <article>.
    <Reveal className={cn('col-span-6', spans[span])}>
      <article className="group/card grid h-full content-start gap-[18px] rounded-2xl bg-surface px-2.5 pt-2.5 pb-[26px] inset-ring inset-ring-line transition-[box-shadow,translate] duration-300 ease-out-strong hover:-translate-y-[3px] hover:inset-ring-line-accent">
        <div
          aria-hidden="true"
          className={cn('relative h-[210px] overflow-hidden rounded-xl bg-canvas', visualClassName)}
        >
          {children}
        </div>
        <h3 className="px-4 font-serif text-[28px] leading-[1.15] tracking-[-0.018em]">{title}</h3>
        <p className={cn('-mt-2.5 px-4 text-[15.5px] text-ink-muted', span === 6 ? 'max-w-[74ch]' : 'max-w-[50ch]')}>{text}</p>
      </article>
    </Reveal>
  )
}

export function FeatureGrid() {
  const titleId = `${sectionIds.features}-title`
  return (
    <section id={sectionIds.features} aria-labelledby={titleId} className="scroll-mt-24 pb-28 max-sm:pb-[72px]">
      <Container>
        <SectionHeading
          id={titleId}
          label="Features"
          title={
            <>
              Your Linux. <em>Your</em> words.
            </>
          }
        />
        <div className="grid grid-cols-6 gap-4">
          <FeatureCard
            span={4}
            title="Say it in words"
            text="Any theme, ricing, compositor, window manager or tool. No preset list to pick from."
          >
            <WordsVisual />
          </FeatureCard>
          <FeatureCard
            title="Try it live first"
            text="The real system runs in a preview. Click around before you commit."
          >
            <LiveVisual />
          </FeatureCard>
          <FeatureCard
            title="Bring your own agent"
            text="Use the model you already pay for, or a local one. Keys never enter the chat."
            visualClassName="h-[300px]"
          >
            <AgentsSignalVisual />
          </FeatureCard>
          <FeatureCard
            span={4}
            title="What you tried is what you get"
            text="The exact system from the preview moves to your computer, with everything you changed in it."
            visualClassName="h-[300px] max-sm:h-[440px]"
          >
            <SameSystemVisual />
          </FeatureCard>
          <FeatureCard
            span={6}
            title="Arch was never this easy"
            text="Any window manager, rice, theme or tool: say it out loud and AGIOS puts the system together the way you meant it. Walk through it in the preview before it ever touches your disk."
            visualClassName="h-auto"
          >
            <AtlasVisual />
          </FeatureCard>
        </div>
      </Container>
    </section>
  )
}
