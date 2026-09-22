import { Bullets } from '../../ui/prose'
import type { DocPage } from '../types'

export const liveEnvironment: DocPage = {
  slug: 'live-environment',
  chapter: 'concepts',
  short: 'Live environment',
  title: 'The live',
  em: 'environment.',
  lede: 'One ISO, built with mkarchiso from the official repositories, that carries the site, the agent bridge and the preview machine.',
  sections: [
    {
      id: 'one-image',
      title: 'One image',
      summary: 'Live ISO assembled by mkarchiso from core and extra with signature checks. The preview machine boots the same medium.',
      content: (
        <p>
          The Live ISO is assembled by <code>mkarchiso</code> from <code>core</code> and <code>extra</code> with
          signature checks. It adds the installer site and the remote-desktop client used for the preview. The inner
          preview machine boots the same medium without graphics, so a second image is never needed.
        </p>
      ),
    },
    {
      id: 'what-runs',
      title: 'What runs where',
      summary: 'Firefox opens the installer at localhost:8787. The controller talks to your agent and validates configuration. The preview is a VM inside the Live system.',
      content: (
        <Bullets>
          <li>
            Firefox opens the installer site at <code>localhost:8787</code>.
          </li>
          <li>The controller talks to your agent and validates every configuration.</li>
          <li>The preview is a virtual machine inside the Live system, shown in the browser.</li>
        </Bullets>
      ),
    },
  ],
}

export const reversiblePreview: DocPage = {
  slug: 'reversible-preview',
  chapter: 'concepts',
  short: 'Reversible preview',
  title: 'A preview you can',
  em: 'undo.',
  lede: 'The preview is the real installed system, kept somewhere you can take back with one action.',
  sections: [
    {
      id: 'why',
      title: 'Why a preview',
      summary: 'Reading a package list is not the same as using a desktop. Launch apps, save files, change settings before anything is written.',
      content: (
        <p>
          Reading a package list is not the same as using a desktop. The preview lets you launch apps, save files and
          change settings before anything is written to your disk.
        </p>
      ),
    },
    {
      id: 'undo',
      title: 'Undo is always one action',
      summary: 'Memory: reboot. File: one file removed. Partition: one entry removed. Shrunk partition: boundary restored and filesystem grows back.',
      content: (
        <Bullets>
          <li>In memory: reboot, and it is gone.</li>
          <li>File on a drive: one file is removed.</li>
          <li>New partition: one entry is removed.</li>
          <li>Shrunk partition: the boundary is restored and the filesystem grows back.</li>
        </Bullets>
      ),
    },
  ],
}

export const agentAndPrivacy: DocPage = {
  slug: 'agent-and-privacy',
  chapter: 'concepts',
  short: 'Agent & privacy',
  title: 'The agent and',
  em: 'your secrets.',
  lede: 'The agent chooses packages and proposes configuration. It never sees your passwords or keys.',
  sections: [
    {
      id: 'sees',
      title: 'What the agent sees',
      summary: 'Your description of the system and the validated configuration. Package choices limited to the official repositories.',
      content: (
        <p>
          Your description of the system and the validated configuration it proposes. Package choices are limited to
          the official repositories.
        </p>
      ),
    },
    {
      id: 'never-sees',
      title: 'What it never sees',
      summary: 'User password and LUKS2 passphrase. API keys stay in memory for the session. The disk path you type when confirming.',
      content: (
        <Bullets>
          <li>Your user password and LUKS2 passphrase, entered in the size-and-place step.</li>
          <li>API keys, which stay in the app's memory for the session.</li>
          <li>The disk path you type when you confirm the install.</li>
        </Bullets>
      ),
    },
  ],
}
