import { createFileRoute } from '@tanstack/react-router'

import { InstallPage } from '@/pages/install'
import { siteConfig } from '@/shared/config'
import { breadcrumbLd, pageHead } from '@/shared/lib/seo'

export const Route = createFileRoute('/install')({
  head: () =>
    pageHead({
      title: `Download ${siteConfig.name} — Live ISO for USB or Virtual Machine`,
      description:
        'Download the free AGI OS Live ISO, check its SHA-256 fingerprint, write it to a USB stick or boot it in a virtual machine. Step by step for Linux, macOS and Windows.',
      path: '/install',
      jsonLd: [
        breadcrumbLd([
          { name: siteConfig.name, path: '/' },
          { name: 'Install', path: '/install' },
        ]),
      ],
    }),
  component: InstallPage,
})
