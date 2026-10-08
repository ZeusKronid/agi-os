import { Bullets } from '../../ui/prose'
import type { DocPage } from '../types'

export const liveEnvironment: DocPage = {
  slug: 'live-environment',
  chapter: 'concepts',
  short: 'Live environment',
  title: 'The live',
  em: 'environment.',
  lede: 'One ISO, built with mkarchiso from the official repositories, that carries the workspace, the agent and the preview machine.',
  metaTitle: 'AGI OS Live Environment — an Arch ISO with an Agent Inside',
  sections: [
    {
      id: 'one-image',
      title: 'One image',
      summary: 'Live ISO assembled by mkarchiso from core and extra with signature checks. Web workspace, Apache Guacamole 1.6.0 client and guacd. The preview VM boots headless from the same media.',
      content: (
        <p>
          The Live ISO is assembled by <code>mkarchiso</code> from <code>core</code> and <code>extra</code> with
          signature checks. It bundles the web workspace, the Apache Guacamole 1.6.0 client and <code>guacd</code>. The
          preview VM boots headless from the same media, so a second image is never needed.
        </p>
      ),
    },
    {
      id: 'what-runs',
      title: 'What runs where',
      summary: 'Firefox opens the workspace at localhost:8787. The controller talks to your model and validates configuration. The preview is a VM inside the Live system, streamed through Guacamole. Passwordless sudo for the agi user.',
      content: (
        <Bullets>
          <li>
            Firefox opens the workspace at <code>localhost:8787</code>.
          </li>
          <li>The controller talks to your model and validates every proposal against the package catalog and your disks.</li>
          <li>The preview is a virtual machine inside the Live system, streamed into the page through Guacamole.</li>
          <li>
            The desktop user <code>agi</code> has passwordless sudo. Changes to the Live system are gone after reboot;
            writes to other drives stay.
          </li>
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
  metaTitle: 'Reversible Preview: Try Your Linux Before Installing — AGI OS',
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
      summary: 'RAM: stop the VM. File: one file removed. Partition: one entry removed. Shrunk partition: boundary restored and filesystem grows back. Disks change only after a typed confirmation.',
      content: (
        <Bullets>
          <li>In RAM: stop the VM, and it is gone.</li>
          <li>File on a drive: one file is removed.</li>
          <li>New partition: one entry is removed.</li>
          <li>Shrunk partition: the boundary is restored and the filesystem grows back.</li>
          <li>Erased disk: no undo. It is offered, but only after an explicit, typed confirmation.</li>
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
  lede: 'The agent chooses packages and proposes configuration. Passwords never reach the model.',
  metaTitle: 'AI Agent Privacy: Where Your Keys Go — AGI OS Docs',
  sections: [
    {
      id: 'sees',
      title: 'What the agent sees',
      summary: 'Your description of the system, the validated configuration and the hardware the page shows. Package choices limited to the official repositories.',
      content: (
        <p>
          Your description of the system, the validated configuration it proposes, and the same hardware summary the
          page shows you: CPU, GPU, network, sound and the drivers AGIOS adds for them. Package choices are limited to
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
          <li>Your user password and LUKS2 passphrase, entered when you place the preview.</li>
          <li>API keys, which stay in the app's memory for the session.</li>
          <li>The disk path you type when you confirm the install.</li>
        </Bullets>
      ),
    },
    {
      id: 'limits',
      title: 'What it may change',
      summary:
        'Configuration files from the agent may not touch accounts, privileges, storage, boot, the package manager or anything that runs as root. What runs at login needs its own confirmation.',
      content: (
        <>
          <p>
            Configuration files the agent proposes may not touch accounts, privileges, storage, boot, the package
            manager or anything that runs as root.
          </p>
          <p>
            Whatever runs when you log in, such as autostart entries or <code>exec</code> lines of a window manager
            config, is listed with the exact lines and needs your own confirmation before the preview is built.
          </p>
        </>
      ),
    },
  ],
}
