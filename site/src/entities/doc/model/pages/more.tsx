import { siteConfig } from '@/shared/config'

import type { DocPage } from '../types'

export const faq: DocPage = {
  slug: 'faq',
  chapter: 'more',
  short: 'FAQ',
  title: 'Questions,',
  em: 'answered.',
  lede: 'Short answers to what people ask before they boot the ISO.',
  sections: [
    {
      id: 'free',
      title: 'Is it free?',
      summary: 'Yes. Open source under the Apache 2.0 license. Your model provider may charge for API usage.',
      content: (
        <p>Yes. AGI OS is open source under the Apache 2.0 license. Your model provider may charge for API usage.</p>
      ),
    },
    {
      id: 'hardware',
      title: 'Will it work on my computer?',
      summary: 'Tested in virtual machines on 64-bit PCs with UEFI. Real hardware is experimental, try a spare machine first.',
      content: (
        <p>
          It is tested in virtual machines on 64-bit PCs with UEFI. Installing on real hardware is still experimental,
          so try a spare machine first.
        </p>
      ),
    },
    {
      id: 'data',
      title: 'What happens to my data?',
      summary: 'Nothing changes until you confirm the install yourself. The install replaces everything on the drive you pick, back up first.',
      content: (
        <p>
          Nothing changes until you confirm the install yourself. The install then replaces everything on the drive you
          pick, so back up first.
        </p>
      ),
    },
    {
      id: 'wrong',
      title: 'What if something goes wrong?',
      summary: 'It tells you where it stopped and leaves things as they are. It never retries by wiping again on its own.',
      content: (
        <p>It tells you where it stopped and leaves things as they are. It never retries by wiping again on its own.</p>
      ),
    },
  ],
}

export const contribute: DocPage = {
  slug: 'contribute',
  chapter: 'more',
  short: 'Contribute',
  title: 'Build it',
  em: 'with us.',
  lede: 'The installer engine, the Live site and these docs live in one public repository.',
  sections: [
    {
      id: 'repository',
      title: 'Repository',
      summary: 'Source, issues and test evidence are on GitHub. Reports and screenshots are delivered outside Git.',
      content: (
        <p>
          Source, issues and test evidence are on <a href={siteConfig.links.repo}>GitHub</a>. Reports and screenshots
          are delivered outside Git.
        </p>
      ),
    },
    {
      id: 'checks',
      title: 'Run the checks',
      summary: 'Unit tests for the installer engine and the web controller run with the standard Python test runner. See the README.',
      content: (
        <p>
          Unit tests for the installer engine and the web controller run with the standard Python test runner. The
          README lists the exact commands and the test VM script.
        </p>
      ),
    },
  ],
}
