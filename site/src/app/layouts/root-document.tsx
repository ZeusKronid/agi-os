import { HeadContent, Scripts } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { ScrollProgress } from '@/features/scroll-progress'
import { sectionIds } from '@/shared/config'
import { mountSmoothScroll } from '@/shared/lib/motion'
import { SiteFooter } from '@/widgets/site-footer'
import { SiteHeader } from '@/widgets/site-header'

export function RootDocument({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body className="bg-canvas bg-stars font-sans text-ink antialiased">
        {/* Callback ref задаёт жизненный цикл Lenis + GSAP ticker: настройка при монтировании, очистка при размонтировании. */}
        <div id={sectionIds.top} ref={mountSmoothScroll} className="flex min-h-dvh flex-col">
          <a
            href={`#${sectionIds.main}`}
            className="sr-only focus:not-sr-only focus:fixed focus:top-4 focus:left-4 focus:z-50 focus:rounded-[7px] focus:bg-accent focus:px-4 focus:py-2 focus:font-mono focus:text-sm focus:text-on-accent"
          >
            Skip to content
          </a>
          <ScrollProgress />
          <SiteHeader />
          <main id={sectionIds.main} className="flex-1">
            {children}
          </main>
          <SiteFooter />
        </div>
        <Scripts />
      </body>
    </html>
  )
}
