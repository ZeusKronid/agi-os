import { Link } from '@tanstack/react-router'

import { InstallDemo } from '@/features/install-demo'
import { sectionIds, siteConfig } from '@/shared/config'
import { ButtonLink, buttonStyles } from '@/shared/ui/button'
import { Container } from '@/shared/ui/container'
import { ArrowDownIcon } from '@/shared/ui/icon'
import { Sunburst } from '@/shared/ui/sunburst'

import { mountLiveSun } from '../lib/mount-live-sun'

// Одна вертикальная ось: лого в шапке → луч восхода → заголовок → подстрочник → кнопки → окно демо.
// Вступление слов, подстрочника, кнопок и окна — CSS с первой отрисовки. Заголовок — горизонт: слова
// поднимаются первыми, а живой восход встаёт из-за них (`Sunburst variant="live"`), когда главный поток
// освободится после гидрации; дальше `mountLiveSun` ведёт лучи: линза к курсору, дыхание, голос демо,
// точки шагов на дуге.
// Масштаб задаёт `--hero-h1` (от ширины и высоты экрана): от него растут восход и окно демо, поэтому
// на любом экране окно начинается примерно на 62–68% высоты и уходит за сгиб, как в прототипе.
export function Hero() {
  return (
    <section
      ref={mountLiveSun}
      aria-labelledby="hero-title"
      className="touch-pan-y pt-[clamp(8px,3vh,48px)] pb-[clamp(28px,3vh,56px)] text-center [--hero-h1:clamp(40px,min(6vw,9.6vh),112px)] [--hero-sun:min(88vw,max(min(620px,70vh),calc(var(--hero-h1)*7.2)))] max-sm:pt-0 max-sm:pb-6"
    >
      {/* Без JS паузу входа солнца снимать некому: пусть играет сразу. */}
      <noscript>
        <style>{'[data-sun-live] *{animation-play-state:running!important}'}</style>
      </noscript>
      <Container className="flex flex-col">
        {/* У `live` viewBox продлён вверх на 90/640 ширины под вытянутые лучи — компенсируем отрицательным отступом. */}
        <Sunburst
          variant="live"
          className="mx-auto -mt-[calc(var(--hero-sun)*90/640)] -mb-4 block h-auto w-(--hero-sun) text-accent"
        />
        <h1
          id="hero-title"
          className="relative font-serif text-(length:--hero-h1) leading-none tracking-[-0.028em] text-balance"
        >
          <span className="inline-block motion-safe:animate-rise">Modern</span>{' '}
          <em className="inline-block tracking-[-0.02em] text-accent motion-safe:animate-rise motion-safe:[animation-delay:90ms]">
            agentic
          </em>{' '}
          <span className="inline-block motion-safe:animate-rise motion-safe:[animation-delay:180ms]">Linux.</span>
        </h1>
        <p className="mt-[clamp(14px,2.2vh,24px)] font-mono text-[length:clamp(11px,0.95vw,13.5px)] tracking-[0.36em] text-ink-muted uppercase motion-safe:animate-rise motion-safe:[animation-delay:520ms] max-sm:leading-[1.7] max-sm:tracking-[0.2em]">
          Infrastructure for a more capable tomorrow.
        </p>
        <div className="mt-[clamp(22px,3.4vh,34px)] flex flex-wrap justify-center gap-5 motion-safe:animate-rise motion-safe:[animation-delay:620ms] max-sm:gap-3">
          <Link to="/install" className={buttonStyles({ className: 'min-w-[200px]' })}>
            Get AGI OS <ArrowDownIcon />
          </Link>
          <ButtonLink href={siteConfig.links.docs} variant="outline" className="min-w-[200px]">
            Read the docs
          </ButtonLink>
        </div>
        <InstallDemo
          id={sectionIds.demo}
          className="mx-auto mt-[clamp(22px,3.6vh,52px)] max-w-[clamp(920px,calc(var(--hero-h1)*10.2),1060px)] motion-safe:animate-rise motion-safe:[animation-delay:760ms]"
        />
      </Container>
    </section>
  )
}
