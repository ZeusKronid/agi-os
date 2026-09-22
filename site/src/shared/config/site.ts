export const sectionIds = {
  main: 'main',
  top: 'top',
  demo: 'how',
  features: 'features',
  faq: 'faq',
  involved: 'involved',
} as const

const repo = 'https://github.com/ZeusKronid/agi-os'

export const siteConfig = {
  name: 'AGI OS',
  title: 'AGI OS — Modern agentic Linux',
  description:
    'Describe the Linux system you want, try the real thing in a live preview, then install it. An Arch Linux live environment with an agent inside.',
  themeColor: '#0b0908',
  license: 'Apache-2.0',
  links: {
    repo,
    docs: `${repo}#readme`,
    // TODO: заменить на страницу релиза с ISO и контрольной суммой, когда она появится.
    download: repo,
    evidence: `${repo}/tree/HEAD/docs/test-results`,
    // TODO: заменить на реальную страницу пожертвований, когда она появится.
    donate: repo,
  },
  nav: [
    { label: 'Features', href: `/#${sectionIds.features}` },
    { label: 'FAQ', href: `/#${sectionIds.faq}` },
    { label: 'Get Involved', href: `/#${sectionIds.involved}` },
  ],
} as const
