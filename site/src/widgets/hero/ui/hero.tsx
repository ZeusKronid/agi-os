import { Link } from '@tanstack/react-router'

import { InstallDemo } from '@/features/install-demo'
import { sectionIds, siteConfig } from '@/shared/config'
import { ButtonLink, buttonStyles } from '@/shared/ui/button'
import { Container } from '@/shared/ui/container'
import { ArrowDownIcon } from '@/shared/ui/icon'
import { Sunburst } from '@/shared/ui/sunburst'

// Одна вертикальная ось: лого в шапке → луч восхода → заголовок → подстрочник → кнопки → окно демо.
// Вступление — чистый CSS (`motion-safe:animate-rise`): стартует с первой отрисовки SSR-разметки,
// не ждёт гидрации и отключается при reduced motion.
// На десктопе секция занимает весь первый экран под шапкой (104px): отступы и высота окна демо
// считаются от высоты вьюпорта, остаток распределяется поровну сверху и снизу, так что marquee
// и следующая секция начинаются только за сгибом.
export function Hero() {
  return (
    <section
      aria-labelledby="hero-title"
      className="flex flex-col pt-[clamp(8px,3vh,48px)] pb-[clamp(28px,3vh,56px)] text-center max-sm:pt-0 max-sm:pb-6 sm:min-h-[calc(100svh-104px)]"
    >
      <Container className="flex flex-1 flex-col justify-center">
        <Sunburst
          variant="hero"
          className="mx-auto -mb-4 block h-auto w-[min(620px,88vw)] text-accent motion-safe:animate-rise"
        />
        <h1
          id="hero-title"
          className="relative font-serif text-[length:clamp(40px,min(6vw,9.6vh),90px)] leading-none tracking-[-0.028em] text-balance motion-safe:animate-rise motion-safe:[animation-delay:80ms]"
        >
          Modern <em className="tracking-[-0.02em] text-accent">agentic</em> Linux.
        </h1>
        <p className="mt-[clamp(14px,2.2vh,24px)] font-mono text-[length:clamp(11px,0.95vw,13.5px)] tracking-[0.36em] text-ink-muted uppercase motion-safe:animate-rise motion-safe:[animation-delay:160ms] max-sm:leading-[1.7] max-sm:tracking-[0.2em]">
          Infrastructure for a more capable tomorrow.
        </p>
        <div className="mt-[clamp(22px,3.4vh,34px)] flex flex-wrap justify-center gap-5 motion-safe:animate-rise motion-safe:[animation-delay:240ms] max-sm:gap-3">
          <Link to="/install" className={buttonStyles({ className: 'min-w-[200px]' })}>
            Get AGI OS <ArrowDownIcon />
          </Link>
          <ButtonLink href={siteConfig.links.docs} variant="outline" className="min-w-[200px]">
            Read the docs
          </ButtonLink>
        </div>
        <InstallDemo
          id={sectionIds.demo}
          className="mx-auto mt-[clamp(22px,3.6vh,52px)] max-w-[920px] motion-safe:animate-rise motion-safe:[animation-delay:320ms]"
        />
      </Container>
    </section>
  )
}
