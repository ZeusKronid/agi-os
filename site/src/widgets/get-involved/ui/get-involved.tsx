import type { ReactNode } from 'react'

import { sectionIds, siteConfig } from '@/shared/config'
import { cn } from '@/shared/lib/cn'
import { Container } from '@/shared/ui/container'
import { ArrowRightIcon, GitHubIcon, HeartIcon } from '@/shared/ui/icon'
import { Reveal } from '@/shared/ui/reveal'
import { SectionHeading } from '@/shared/ui/section-heading'

interface ActionCardProps {
  href: string
  title: string
  text: string
  action: string
  icon: ReactNode
  tone: 'fill' | 'line'
}

function ActionCard({ href, title, text, action, icon, tone }: ActionCardProps) {
  const fill = tone === 'fill'
  return (
    <Reveal className="h-full">
      <a
        href={href}
        className={cn(
          'group/cta relative isolate grid h-full min-h-[280px] content-between gap-8 overflow-hidden rounded-2xl p-8 transition-[translate,background-color,box-shadow] duration-300 ease-out-strong hover:-translate-y-1 active:-translate-y-px max-sm:min-h-60 max-sm:p-[26px]',
          fill
            ? 'bg-accent text-on-accent hover:bg-accent-hover'
            : 'bg-surface inset-ring inset-ring-line-accent hover:inset-ring-accent',
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            'absolute -top-9 -right-11 -z-10 size-[250px] transition-[rotate,scale] duration-700 ease-out-strong group-hover/cta:scale-[1.04] group-hover/cta:-rotate-[8deg] [&_svg]:size-full',
            fill ? 'opacity-[0.12]' : 'text-accent opacity-[0.09]',
          )}
        >
          {icon}
        </span>
        <span
          className={cn(
            'grid size-11 place-items-center rounded-[14px] [&_svg]:size-[22px]',
            fill ? 'bg-on-accent/15' : 'bg-accent-soft text-accent',
          )}
        >
          {icon}
        </span>
        <span className="block">
          <span className="block font-serif text-[clamp(34px,3.8vw,48px)] leading-[1.05] tracking-[-0.024em]">
            {title}
          </span>
          <span className={cn('mt-2.5 block max-w-[32ch]', fill ? 'text-on-accent/80' : 'text-ink-muted')}>
            {text}
          </span>
        </span>
        <span className="flex items-center justify-between gap-4 font-mono text-[13px] font-medium">
          {action}
          <span
            aria-hidden="true"
            className={cn(
              'grid size-12 place-items-center rounded-full transition-[scale] duration-300 ease-out-strong group-hover/cta:scale-[1.06]',
              fill ? 'bg-on-accent text-accent' : 'bg-accent text-on-accent',
            )}
          >
            <ArrowRightIcon className="size-[18px] -rotate-45 transition-[rotate] duration-300 ease-out-strong group-hover/cta:rotate-0" />
          </span>
        </span>
      </a>
    </Reveal>
  )
}

export function GetInvolved() {
  const titleId = `${sectionIds.involved}-title`
  return (
    <section id={sectionIds.involved} aria-labelledby={titleId} className="scroll-mt-24 pb-28 max-sm:pb-[72px]">
      <Container>
        <SectionHeading
          id={titleId}
          label="Get involved"
          title={
            <>
              Build it <em>with us.</em>
            </>
          }
        />
        <div className="grid gap-4 lg:grid-cols-2">
          <ActionCard
            tone="fill"
            href={siteConfig.links.repo}
            title="Contribute"
            text="File issues, fix bugs, and ship features with us."
            action="Open on GitHub"
            icon={<GitHubIcon />}
          />
          <ActionCard
            tone="line"
            href={siteConfig.links.donate}
            title="Donate"
            text="Fund the people and the test hardware behind AGI OS."
            action="Become a patron"
            icon={<HeartIcon />}
          />
        </div>
      </Container>
    </section>
  )
}
