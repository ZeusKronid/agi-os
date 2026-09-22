import { useId, useState } from 'react'

import { sectionIds, siteConfig } from '@/shared/config'
import { ButtonLink } from '@/shared/ui/button'
import { Container } from '@/shared/ui/container'
import { ArrowRightIcon, ChevronDownIcon } from '@/shared/ui/icon'
import { Reveal } from '@/shared/ui/reveal'
import { SectionHeading } from '@/shared/ui/section-heading'

import { faqColumns, type FaqItem } from '../model/faq'

interface FaqColumnProps {
  items: readonly FaqItem[]
  defaultOpen: number | null
}

/** Колонка аккордеона: одновременно открыт не более чем один вопрос. */
function FaqColumn({ items, defaultOpen }: FaqColumnProps) {
  const [open, setOpen] = useState<number | null>(defaultOpen)
  const baseId = useId()

  return (
    <div>
      {items.map((item, index) => {
        const isOpen = open === index
        const panelId = `${baseId}-panel-${index}`
        const buttonId = `${baseId}-button-${index}`
        return (
          <div key={item.question} className="border-b border-line">
            <h3>
              <button
                id={buttonId}
                type="button"
                aria-expanded={isOpen}
                aria-controls={panelId}
                onClick={() => setOpen(isOpen ? null : index)}
                className="flex w-full items-center justify-between gap-4 py-[22px] text-left font-serif text-[22px] tracking-[-0.012em] transition-colors duration-200 hover:text-accent-hover max-sm:text-[19px]"
              >
                {item.question}
                <ChevronDownIcon
                  data-open={isOpen}
                  className="size-4 shrink-0 text-ink-muted transition-[rotate,color] duration-200 ease-out-strong data-[open=true]:rotate-180 data-[open=true]:text-accent"
                />
              </button>
            </h3>
            <div
              id={panelId}
              role="region"
              aria-labelledby={buttonId}
              inert={!isOpen}
              data-open={isOpen}
              className="grid grid-rows-[0fr] transition-[grid-template-rows] duration-300 ease-out-strong data-[open=true]:grid-rows-[1fr]"
            >
              <div className="overflow-hidden">
                <p className="max-w-[54ch] pb-6 text-[15.5px] leading-[1.6] text-ink-muted">{item.answer}</p>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function Faq() {
  const titleId = `${sectionIds.faq}-title`
  return (
    <section id={sectionIds.faq} aria-labelledby={titleId} className="scroll-mt-24 pb-28 max-sm:pb-[72px]">
      <Container>
        <SectionHeading
          id={titleId}
          label="Frequently asked questions"
          title={
            <>
              Good to know <em>before</em> you start
            </>
          }
        >
          <p className="max-w-[460px] text-[16.5px] text-ink-muted">
            How it works, what it runs on, and what is still experimental.
          </p>
          <ButtonLink href={siteConfig.links.docs} variant="outline">
            Read the docs <ArrowRightIcon />
          </ButtonLink>
        </SectionHeading>
        <Reveal className="grid items-start gap-x-16 lg:grid-cols-2">
          {faqColumns.map((items, index) => (
            <FaqColumn key={index} items={items} defaultOpen={index === 0 ? 0 : null} />
          ))}
        </Reveal>
      </Container>
    </section>
  )
}
