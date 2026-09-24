import { createFileRoute } from '@tanstack/react-router'

import { InstallPage } from '@/pages/install'
import { siteConfig } from '@/shared/config'

export const Route = createFileRoute('/install')({
  head: () => ({
    meta: [
      { title: `Install — ${siteConfig.name}` },
      {
        name: 'description',
        content: 'Download the AGI OS Live ISO, check its fingerprint, write it to a USB stick or boot it in a virtual machine.',
      },
    ],
  }),
  component: InstallPage,
})
