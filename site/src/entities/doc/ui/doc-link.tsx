import { Link, type LinkProps } from '@tanstack/react-router'
import type { ComponentProps } from 'react'

import { docIndexPage } from '../model/docs'
import type { DocPage } from '../model/types'

interface DocLinkProps extends Omit<ComponentProps<'a'>, 'href'> {
  page: DocPage
  hash?: string
  activeProps?: LinkProps['activeProps']
}

/** Ссылка на страницу документации: обзор живёт на `/docs`, остальные — на `/docs/<slug>`. */
export function DocLink({ page, hash, ...props }: DocLinkProps) {
  if (page.slug === docIndexPage.slug) {
    return <Link to="/docs" hash={hash} activeOptions={{ exact: true }} {...props} />
  }
  return <Link to="/docs/$slug" params={{ slug: page.slug }} hash={hash} {...props} />
}
