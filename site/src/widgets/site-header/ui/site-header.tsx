import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { siteConfig } from '@/shared/config'
import { ButtonLink } from '@/shared/ui/button'
import { Container } from '@/shared/ui/container'
import { ArrowDownIcon } from '@/shared/ui/icon'
import { Logo } from '@/shared/ui/logo'

import { mountHeaderScroll } from '../lib/mount-header-scroll'

const MENU_ID = 'site-menu'
const navLinkStyles = 'font-serif text-[17px] text-ink-soft transition-colors duration-200 hover:text-ink'

// Без бордеров. Раскладка: ссылки слева, знак по центру (ось hero), действие справа.
export function SiteHeader() {
  const [open, setOpen] = useState(false)

  return (
    <header
      ref={mountHeaderScroll}
      data-scrolled="false"
      className="sticky top-0 z-40 transition-[background-color] duration-300 data-[scrolled=true]:bg-canvas/85 data-[scrolled=true]:backdrop-blur-md"
    >
      <Container className="grid h-[72px] grid-cols-[1fr_auto] items-center gap-6 sm:h-[104px] sm:grid-cols-[1fr_auto_1fr]">
        <Link to="/" aria-label={`${siteConfig.name} home`} className="justify-self-start text-ink sm:order-2 sm:justify-self-center">
          <Logo className="h-[22px] w-auto sm:h-8" />
        </Link>

        <nav
          id={MENU_ID}
          aria-label="Primary"
          data-open={open}
          className="max-sm:absolute max-sm:inset-x-0 max-sm:top-[72px] max-sm:hidden max-sm:bg-canvas max-sm:px-4 max-sm:pt-4 max-sm:pb-7 max-sm:data-[open=true]:block sm:order-1"
        >
          <ul className="flex gap-[38px] max-sm:flex-col max-sm:gap-4">
            {siteConfig.nav.map((item) => (
              <li key={item.label}>
                {'href' in item ? (
                  /* Обычный <a>: плавный переход к якорю перехватывает Lenis (`anchors: true`),
                     без Lenis (reduced motion) срабатывает нативный переход. */
                  <a href={item.href} onClick={() => setOpen(false)} className={navLinkStyles}>
                    {item.label}
                  </a>
                ) : (
                  /* Отдельная страница (например, /docs): клиентский переход роутера, активная — Ink. */
                  <Link
                    to={item.to}
                    onClick={() => setOpen(false)}
                    className={navLinkStyles}
                    activeProps={{ className: `${navLinkStyles} text-ink`, 'aria-current': 'page' }}
                  >
                    {item.label}
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </nav>

        <div className="flex items-center gap-3 justify-self-end sm:order-3">
          <ButtonLink href={siteConfig.links.download} size="sm" className="max-sm:hidden">
            Get AGI OS <ArrowDownIcon />
          </ButtonLink>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={MENU_ID}
            onClick={() => setOpen((value) => !value)}
            className="py-1.5 font-serif text-base text-ink-soft sm:hidden"
          >
            {open ? 'Close' : 'Menu'}
          </button>
        </div>
      </Container>
    </header>
  )
}
