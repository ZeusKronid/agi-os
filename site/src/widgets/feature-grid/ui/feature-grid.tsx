import type { ReactNode } from 'react'

import { sectionIds } from '@/shared/config'
import { cn } from '@/shared/lib/cn'
import { Container } from '@/shared/ui/container'
import { Reveal } from '@/shared/ui/reveal'
import { SectionHeading } from '@/shared/ui/section-heading'

import { AgentsSignalVisual } from './agents-signal'
import { LiveVisual } from './live-visual'
import { SameSystemVisual } from './same-system-visual'
import { WordsVisual } from './words-visual'

interface FeatureCardProps {
  title: string
  text: string
  wide?: boolean
  /** Дополнительные классы области визуала, например другая высота. */
  visualClassName?: string
  children: ReactNode
}

function FeatureCard({ title, text, wide, visualClassName, children }: FeatureCardProps) {
  return (
    // Reveal трансформирует внешний узел через GSAP, поэтому hover-сдвиг живёт на внутреннем <article>.
    <Reveal className={cn('col-span-6', wide ? 'lg:col-span-4' : 'lg:col-span-2')}>
      <article className="group/card grid h-full content-start gap-[18px] rounded-2xl bg-surface px-2.5 pt-2.5 pb-[26px] inset-ring inset-ring-line transition-[box-shadow,translate] duration-300 ease-out-strong hover:-translate-y-[3px] hover:inset-ring-line-accent">
        <div
          aria-hidden="true"
          className={cn('relative h-[210px] overflow-hidden rounded-xl bg-canvas', visualClassName)}
        >
          {children}
        </div>
        <h3 className="px-4 font-serif text-[28px] leading-[1.15] tracking-[-0.018em]">{title}</h3>
        <p className="-mt-2.5 max-w-[50ch] px-4 text-[15.5px] text-ink-muted">{text}</p>
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
            wide
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
            wide
            title="What you tried is what you get"
            text="The exact system from the preview moves to your computer, with everything you changed in it."
            visualClassName="h-[300px] max-sm:h-[440px]"
          >
            <SameSystemVisual />
          </FeatureCard>
        </div>
      </Container>
    </section>
  )
}
