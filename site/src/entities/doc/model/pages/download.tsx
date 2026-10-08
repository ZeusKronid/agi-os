import { siteConfig } from '@/shared/config'
import { CommandLine } from '@/shared/ui/command-line'

import { DocTable, Note } from '../../ui/prose'
import type { DocPage } from '../types'

const releases = `${siteConfig.links.repo}/releases`
const downloadGuide = `${siteConfig.links.repo}/blob/HEAD/docs/download.md`
const isoRuns = `${siteConfig.links.repo}/actions/workflows/iso.yml?query=branch%3Amain`

// Факты — из README и docs/download.md. Отпечаток ключа должен совпадать с опубликованным в репозитории.
export const download: DocPage = {
  slug: 'download',
  chapter: 'start',
  short: 'Download & verify',
  title: 'Download and',
  em: 'verify.',
  lede: 'Signed releases are on GitHub. Check the signature before you write the stick.',
  metaTitle: 'Download and Verify the AGI OS Live ISO — Signed Releases',
  metaDescription:
    'Download a signed AGIOS release, verify the ISO with the release key fingerprint, or take an untested build from main.',
  sections: [
    {
      id: 'releases',
      title: 'Signed releases',
      summary: 'Releases page on GitHub: ISO, OpenPGP signatures, SHA256SUMS, release key, build-info.json.',
      content: (
        <>
          <p>
            Signed releases are on the <a href={releases}>Releases page</a>. Each one is built by CI from a version tag
            and carries:
          </p>
          <DocTable
            head={['File', 'What it is']}
            rows={[
              [<code key="iso">agi-os-…-x86_64.iso</code>, 'The Live image'],
              [<code key="sig">….iso.sig</code>, 'OpenPGP signature of the ISO'],
              [<code key="sums">SHA256SUMS</code>, 'Checksums, with its own .sig'],
              [<code key="key">agios-release-key.asc</code>, 'The public signing key'],
              [<code key="info">build-info.json</code>, 'Build inputs: commit, Arch snapshot, container'],
            ]}
          />
          <p>
            Writing the stick or booting a VM is covered on the <a href={siteConfig.links.install}>install page</a>.
          </p>
        </>
      ),
    },
    {
      id: 'verify',
      title: 'Verify before writing the stick',
      summary:
        'python3 scripts/release/verify-iso.py from a checkout of the repository. Release key fingerprint BA1D BAF6 09C7 6719 47DD A5E4 D1DF F581 C1F8 77D3. Plain gpg steps.',
      content: (
        <>
          <p>From a checkout of the repository:</p>
          <CommandLine text="python3 scripts/release/verify-iso.py agi-os-*.iso" />
          <p>
            It uses a temporary keyring, accepts only signatures made by the release key and compares the ISO with{' '}
            <code>SHA256SUMS</code>.
          </p>
          <Note label="Release key fingerprint">
            <p>
              <code>BA1D BAF6 09C7 6719 47DD A5E4 D1DF F581 C1F8 77D3</code>
            </p>
          </Note>
          <p>
            Plain <code>gpg</code> steps for Linux, macOS and Windows are in{' '}
            <a href={downloadGuide}>download and verification</a>.
          </p>
        </>
      ),
    },
    {
      id: 'main-builds',
      title: 'Untested builds from main',
      summary: 'Live ISO workflow runs, agi-os-iso artifact, GitHub sign-in required, kept for 7 days.',
      content: (
        <p>
          Untested builds from <code>main</code> are attached to <a href={isoRuns}>Live ISO workflow runs</a> as the{' '}
          <code>agi-os-iso</code> artifact. Downloading needs a GitHub sign-in, and artifacts are kept for 7 days. Their
          checksum detects a damaged download but is not a signature.
        </p>
      ),
    },
  ],
}
