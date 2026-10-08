import { siteConfig } from '@/shared/config'
import { CommandLine } from '@/shared/ui/command-line'

import { Bullets, DocTable } from '../../ui/prose'
import type { DocPage } from '../types'

const repoDoc = (file: string) => `${siteConfig.links.repo}/blob/HEAD/docs/${file}`

export const faq: DocPage = {
  slug: 'faq',
  chapter: 'more',
  short: 'FAQ',
  title: 'Questions,',
  em: 'answered.',
  lede: 'Short answers to what people ask before they boot the ISO.',
  metaTitle: 'AGI OS FAQ — Agentic Arch Linux Questions Answered',
  metaDescription:
    'Is AGIOS free, will it run on my computer, what happens to my data and where do API keys go: short answers before you boot the ISO.',
  sections: [
    {
      id: 'free',
      title: 'Is it free?',
      summary: 'Yes. Open source under the Apache 2.0 license. Your model provider may charge for API usage.',
      content: (
        <p>Yes. AGIOS is open source under the Apache 2.0 license. Your model provider may charge for API usage.</p>
      ),
    },
    {
      id: 'hardware',
      title: 'Will it work on my computer?',
      summary: 'A 64-bit PC with UEFI or BIOS. Tested in virtual machines; real hardware is experimental, try a spare machine first.',
      content: (
        <p>
          It needs a 64-bit PC with UEFI or BIOS. AGIOS is tested in virtual machines; installing on real hardware is
          still experimental, so try a spare machine first.
        </p>
      ),
    },
    {
      id: 'data',
      title: 'What happens to my data?',
      summary:
        'Nothing changes until a typed confirmation. Install next to your files and other systems, or erase the disk. Back up first.',
      content: (
        <p>
          Nothing changes until you confirm with the disk path. You can install next to your files and other systems,
          or erase the disk. Back up first either way.
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
  short: 'Build & contribute',
  title: 'Build it',
  em: 'from source.',
  lede: 'The installer engine, the Live workspace and this site live in one public repository.',
  metaTitle: 'Build AGI OS from Source and Contribute on GitHub',
  metaDescription:
    'Build the AGIOS Live ISO with mkarchiso, make reproducible builds, run the tests and find your way around the repository.',
  sections: [
    {
      id: 'build',
      title: 'Build the ISO',
      summary:
        'sudo ./scripts/build-iso.sh, out/agi-os-date-x86_64.iso about 2 GB. mkarchiso from core and extra with signature checks. Guacamole 1.6.0 client and guacd.',
      content: (
        <>
          <CommandLine text="sudo ./scripts/build-iso.sh" />
          <p>
            The result is <code>out/agi-os-&lt;date&gt;-x86_64.iso</code>, about 2&nbsp;GB: one ISO built by{' '}
            <code>mkarchiso</code> from the official <code>core</code> and <code>extra</code> repositories with
            signature checks. It bundles the web workspace, the Guacamole 1.6.0 client and <code>guacd</code>; the
            preview VM boots headless from the same media.
          </p>
        </>
      ),
    },
    {
      id: 'reproducible',
      title: 'Reproducible builds',
      summary: 'scripts/ci/build-iso.sh uses a pinned Arch container and an Arch Linux Archive snapshot.',
      content: (
        <p>
          <code>scripts/ci/build-iso.sh</code> uses a pinned Arch container and an Arch Linux Archive snapshot. See{' '}
          <a href={repoDoc('ci.md')}>CI and builds</a>.
        </p>
      ),
    },
    {
      id: 'development',
      title: 'Development',
      summary:
        'Unit tests for the installer engine and the web workspace, node --check, run-live-web-vm.sh to boot the Live ISO or the installed disk in a test VM.',
      content: (
        <>
          <p>Tests for the installer engine and the web workspace:</p>
          <CommandLine text="python -B -m unittest discover -s tests -v" />
          <CommandLine text=".local/venv/bin/python -B -m unittest discover -s web/tests -v" />
          <CommandLine text="node --check web/static/app.js" />
          <p>
            The Live ISO in a test VM (<code>--firmware bios</code> and <code>--memory 16384</code> are optional), then
            the installed disk:
          </p>
          <CommandLine text="./scripts/run-live-web-vm.sh" />
          <CommandLine text="./scripts/run-live-web-vm.sh --mode disk" />
        </>
      ),
    },
    {
      id: 'layout',
      title: 'Repository layout',
      summary: 'Shared installer engine in archiso airootfs, web workspace server, workspace UI in web/static, project website in site.',
      content: (
        <DocTable
          head={['Path', 'What']}
          rows={[
            [<code key="engine">archiso/…/agi-os/installer/</code>, 'Shared installer engine'],
            [<code key="web">web/</code>, 'Workspace server, preview storage, finalization'],
            [<code key="static">web/static/</code>, 'Workspace UI'],
            [<code key="site">site/</code>, 'Project website'],
          ]}
        />
      ),
    },
    {
      id: 'reference',
      title: 'Reference docs',
      summary:
        'Live, preview and finalization. Installer architecture. Testing an installed system. Development model bridge. CI and builds. Download and verification.',
      content: (
        <Bullets>
          <li>
            <a href={repoDoc('local-web.md')}>Live, preview and finalization</a>
          </li>
          <li>
            <a href={repoDoc('installer-architecture.md')}>Installer architecture</a>
          </li>
          <li>
            <a href={repoDoc('installation-testing.md')}>Testing an installed system</a>
          </li>
          <li>
            <a href={repoDoc('development-bridge.md')}>Development model bridge</a>
          </li>
          <li>
            <a href={repoDoc('ci.md')}>CI and builds</a>
          </li>
          <li>
            <a href={repoDoc('download.md')}>Download and verification</a>
          </li>
        </Bullets>
      ),
    },
    {
      id: 'license',
      title: 'License',
      summary:
        'Apache-2.0. The Archiso-based profile keeps GPL-3.0-or-later. Guacamole and other packages keep their own licenses.',
      content: (
        <p>
          Apache-2.0. The Archiso-based profile keeps GPL-3.0-or-later. Guacamole and other packages in the image keep
          their own licenses; Guacamole&apos;s LICENSE and NOTICE ship in the Live ISO. Source and issues are on{' '}
          <a href={siteConfig.links.repo}>GitHub</a>.
        </p>
      ),
    },
  ],
}
