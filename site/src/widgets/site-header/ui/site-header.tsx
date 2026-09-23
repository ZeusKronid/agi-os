import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { siteConfig } from '@/shared/config'
import { buttonStyles } from '@/shared/ui/button'
import { Container } from '@/shared/ui/container'
import { ArrowDownIcon, GitHubIcon } from '@/shared/ui/icon'
import { Logo } from '@/shared/ui/logo'

import { mountHeaderScroll } from '../lib/mount-header-scroll'

const MENU_ID = 'site-menu'
const navLinkStyles = 'font-serif text-[17px] text-ink-soft transition-colors duration-200 hover:text-ink'

// Без бордеров. Раскладка: ссылки слева, знак по центру (ось hero), действие справа.
// На входе элементы опускаются на место (CSS с первой отрисовки, вместе со словами hero): знак первым,
// ссылки лесенкой, кнопка последней. Анимируются дети, а не сама липкая шапка — её фон и blur не трогаем.
export function SiteHeader() {
  const [open, setOpen] = useState(false)

  return (
    <header
      ref={mountHeaderScroll}
      data-scrolled="false"
      className="sticky top-0 z-40 transition-[background-color] duration-300 data-[scrolled=true]:bg-canvas/95"
    >
      <Container className="grid h-[72px] grid-cols-[1fr_auto] items-center gap-6 sm:h-[104px] sm:grid-cols-[1fr_auto_1fr]">
        <Link to="/" aria-label={`${siteConfig.name} home`} className="justify-self-start text-ink motion-safe:animate-drop sm:order-2 sm:justify-self-center">
          <Logo className="h-[22px] w-auto sm:h-8" />
        </Link>

        <nav
          id={MENU_ID}
          aria-label="Primary"
          data-open={open}
          className="max-sm:absolute max-sm:inset-x-0 max-sm:top-[72px] max-sm:hidden max-sm:bg-canvas max-sm:px-4 max-sm:pt-4 max-sm:pb-7 max-sm:data-[open=true]:block sm:order-1"
        >
          <ul className="flex gap-[38px] max-sm:flex-col max-sm:gap-4">
            {siteConfig.nav.map((item, index) => (
              <li
                key={item.label}
                className="motion-safe:animate-drop"
                style={{ animationDelay: `${80 + index * 50}ms` }}
              >
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

        <div className="flex items-center gap-3 justify-self-end motion-safe:animate-drop motion-safe:[animation-delay:260ms] sm:order-3 sm:gap-5">
          <a
            href={siteConfig.links.repo}
            aria-label={`${siteConfig.name} on GitHub`}
            className="text-ink-muted transition-colors duration-200 hover:text-ink"
          >
            <GitHubIcon className="size-[22px]" />
          </a>
          <Link to="/install" className={buttonStyles({ size: 'sm', className: 'max-sm:hidden' })}>
            Get AGI OS <ArrowDownIcon />
          </Link>
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
