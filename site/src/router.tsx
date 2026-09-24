import { createRouter } from '@tanstack/react-router'

import { NotFoundPage } from '@/pages/not-found'

// Файл генерируется плагином TanStack Start при `npm run dev` / `npm run build` — руками не править.
import { routeTree } from './routeTree.gen'

export function getRouter() {
  const router = createRouter({
    routeTree,
    scrollRestoration: true,
    defaultPreload: 'intent',
    defaultNotFoundComponent: NotFoundPage,
  })

  return router
}
