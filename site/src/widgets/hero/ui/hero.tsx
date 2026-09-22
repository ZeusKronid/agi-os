import { Link } from '@tanstack/react-router'

import { InstallDemo } from '@/features/install-demo'
import { sectionIds, siteConfig } from '@/shared/config'
import { ButtonLink, buttonStyles } from '@/shared/ui/button'
import { Container } from '@/shared/ui/container'
import { ArrowDownIcon } from '@/shared/ui/icon'
import { Sunburst } from '@/shared/ui/sunburst'

import { mountLiveSun } from '../lib/mount-live-sun'

// Одна вертикальная ось: лого в шапке → луч восхода → заголовок → подстрочник → кнопки → окно демо.
// Вступление — чистый CSS: стартует с первой отрисовки SSR-разметки и не ждёт гидрации. Заголовок —
// горизонт: слова поднимаются первыми, а живой восход встаёт из-за них (`Sunburst variant="live"`).
// После гидрации `mountLiveSun` ведёт лучи: линза к курсору, дыхание, голос демо, точки шагов на дуге.
// На десктопе секция занимает весь первый экран под шапкой (104px): отступы и высота окна демо
// считаются от высоты вьюпорта, остаток распределяется поровну сверху и снизу, так что marquee
// и следующая секция начинаются только за сгибом.
export function Hero() {
  return (
    <section
      ref={mountLiveSun}
      aria-labelledby="hero-title"
      className="flex touch-pan-y flex-col pt-[clamp(8px,3vh,48px)] pb-[clamp(28px,3vh,56px)] text-center max-sm:pt-0 max-sm:pb-6 sm:min-h-[calc(100svh-104px)]"
    >
      <Container className="flex flex-1 flex-col justify-center">
        {/* У `live` viewBox продлён вверх на 90/640 ширины под вытянутые лучи — компенсируем отрицательным отступом. */}
        <Sunburst
          variant="live"
          className="mx-auto -mt-[calc(min(620px,88vw)*90/640)] -mb-4 block h-auto w-[min(620px,88vw)] text-accent"
        />
        <h1
          id="hero-title"
          className="relative font-serif text-[length:clamp(40px,min(6vw,9.6vh),90px)] leading-none tracking-[-0.028em] text-balance"
        >
          <span className="inline-block motion-safe:animate-rise">Modern</span>{' '}
          <em className="inline-block tracking-[-0.02em] text-accent motion-safe:animate-rise motion-safe:[animation-delay:90ms]">
            agentic
          </em>{' '}
          <span className="inline-block motion-safe:animate-rise motion-safe:[animation-delay:180ms]">Linux.</span>
        </h1>
        <p className="mt-[clamp(14px,2.2vh,24px)] font-mono text-[length:clamp(11px,0.95vw,13.5px)] tracking-[0.36em] text-ink-muted uppercase motion-safe:animate-rise motion-safe:[animation-delay:300ms] max-sm:leading-[1.7] max-sm:tracking-[0.2em]">
          Infrastructure for a more capable tomorrow.
        </p>
        <div className="mt-[clamp(22px,3.4vh,34px)] flex flex-wrap justify-center gap-5 motion-safe:animate-rise motion-safe:[animation-delay:380ms] max-sm:gap-3">
          <Link to="/install" className={buttonStyles({ className: 'min-w-[200px]' })}>
            Get AGI OS <ArrowDownIcon />
          </Link>
          <ButtonLink href={siteConfig.links.docs} variant="outline" className="min-w-[200px]">
            Read the docs
          </ButtonLink>
        </div>
        <InstallDemo
          id={sectionIds.demo}
          className="mx-auto mt-[clamp(22px,3.6vh,52px)] max-w-[920px] motion-safe:animate-rise motion-safe:[animation-delay:480ms]"
        />
      </Container>
    </section>
  )
}
