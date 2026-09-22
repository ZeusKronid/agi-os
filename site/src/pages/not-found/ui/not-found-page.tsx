import { Link } from '@tanstack/react-router'

import { buttonStyles } from '@/shared/ui/button'
import { Container } from '@/shared/ui/container'

export function NotFoundPage() {
  return (
    <Container className="flex min-h-[calc(100dvh-104px)] flex-col items-center justify-center gap-6 py-24 text-center">
      <p className="font-mono text-xs tracking-[0.36em] text-ink-muted uppercase">404</p>
      <h1 className="font-serif text-[clamp(36px,4.5vw,60px)] leading-[1.04] tracking-[-0.024em] text-balance">
        This page does not exist.
      </h1>
      <Link to="/" className={buttonStyles({ variant: 'outline' })}>
        Back to home
      </Link>
    </Container>
  )
}
