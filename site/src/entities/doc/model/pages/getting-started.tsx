import { siteConfig } from '@/shared/config'
import { CommandLine } from '@/shared/ui/command-line'

import { Bullets, DocTable, Note } from '../../ui/prose'
import type { DocPage } from '../types'

// Факты — из README и FAQ: что подтверждено прогонами в VM, что пока экспериментально.
export const gettingStarted: DocPage = {
  slug: 'getting-started',
  chapter: 'start',
  short: 'Overview',
  title: 'Getting',
  em: 'started.',
  lede: 'From a downloaded ISO to a system that is yours in six steps. Nothing on your disk changes until you confirm the install yourself.',
  sections: [
    {
      id: 'what-is',
      title: 'What is AGI OS',
      summary:
        'An Arch Linux distribution with an agent inside the live environment. Name from the Greek hagios, holy, set apart. Official repositories core and extra. Apache 2.0.',
      content: (
        <>
          <p>
            <strong>AGI OS</strong> is an Arch Linux distribution with an agent inside the live environment. You
            describe the system you want in plain words, watch it get built into a live preview, and install it only
            when you like what you see.
          </p>
          <p>
            The name comes from the Greek <em className="font-serif text-[1.05em] text-ink not-italic">ἅγιος</em>{' '}
            (hágios): holy, set apart. Software comes from the official Arch repositories, <code>core</code> and{' '}
            <code>extra</code>. The project is open source under the Apache&nbsp;2.0 license.
          </p>
          <Note label="In one line">
            <p>Say it in words · try it live · install what you tried.</p>
          </Note>
        </>
      ),
    },
    {
      id: 'requirements',
      title: 'Before you begin',
      summary: 'A 64-bit UEFI PC, tested in virtual machines, real hardware experimental. USB stick or VM. Your own agent. A backup.',
      content: (
        <Bullets>
          <li>
            A 64-bit PC with UEFI. AGI OS is tested in virtual machines; installing on real hardware is still
            experimental, so start with a spare machine.
          </li>
          <li>A USB stick or a virtual machine to boot the ISO from. The image is about 2&nbsp;GB.</li>
          <li>
            An agent to connect: a ChatGPT account, an API key from OpenAI, Anthropic or Gemini, a local Ollama, or any
            OpenAI-compatible endpoint.
          </li>
          <li>A backup of anything you care about on the target drive.</li>
        </Bullets>
      ),
    },
    {
      id: 'boot',
      title: 'Boot the ISO',
      summary: 'Download the image, write it to a USB stick or attach it to a VM, boot. Firefox opens the installer at localhost:8787.',
      content: (
        <>
          <p>
            <a href={siteConfig.links.install}>Download the image</a>, write it to a USB stick or attach it to a
            virtual machine, and boot. A Firefox window opens the installer by itself. At this point nothing on your
            disk has changed.
          </p>
          <p>The installer lives on the Live system and is served locally:</p>
          <CommandLine text="http://localhost:8787" />
        </>
      ),
    },
    {
      id: 'connect',
      title: 'Connect your agent',
      summary:
        'ChatGPT sign-in, OpenAI API key, Anthropic, Gemini, Ollama local, OpenAI-compatible endpoint. Keys stay in memory for the session.',
      content: (
        <>
          <p>Choose how the agent signs in. Nothing is bundled: you bring the model you already use.</p>
          <DocTable
            head={['Agent', 'Way in']}
            rows={[
              ['ChatGPT', 'Sign in with your account'],
              ['OpenAI API', 'API key'],
              ['Anthropic', 'API key'],
              ['Gemini', 'API key'],
              ['Ollama', 'Local models, no key'],
              ['Compatible endpoint', 'Any OpenAI-compatible URL'],
            ]}
          />
          <Note label="Privacy">
            <p>
              Keys stay in the app's memory for the session. They are never sent into the chat and never copied to the
              installed system. Your provider may charge for API usage.
            </p>
          </Note>
        </>
      ),
    },
    {
      id: 'describe',
      title: 'Describe your system',
      summary:
        'Desktop or window manager, theme, tools, languages, keyboard layouts, or no desktop at all. Packages from the official repositories, checked before the build.',
      content: (
        <>
          <p>
            Tell the agent what you want: a desktop or a window manager, a theme, tools, languages, keyboard layouts, or
            no desktop at all. The agent picks packages from the official repositories and proposes a configuration;
            the app checks it before anything is built.
          </p>
          <Note label="Example">
            <p>“Hyprland, dark theme, neovim, docker and waybar.”</p>
          </Note>
        </>
      ),
    },
    {
      id: 'preview',
      title: 'Try it in a live preview',
      summary:
        'Calculate size and place: memory zram, file on a drive, new partition, shrink NTFS or ext4, erase disk. User password and LUKS2 passphrase. Revert everything.',
      content: (
        <>
          <p>
            Press <strong>Calculate size and place</strong>. The app computes the exact size of the system from package
            data and offers where to keep the preview:
          </p>
          <Bullets>
            <li>
              <strong>In memory</strong> as a compressed zram image. Disks are not touched.
            </li>
            <li>
              <strong>As a file</strong> on any drive with a filesystem: a USB stick, a second disk, an SD card. Undo
              removes one file.
            </li>
            <li>
              <strong>As a new partition</strong> in unallocated space. Undo removes one entry.
            </li>
            <li>
              <strong>By shrinking</strong> an NTFS or ext4 partition on the target disk, after a dry run and a separate
              confirmation. Undo restores the boundary.
            </li>
            <li>
              <strong>By erasing the disk now.</strong> Only explicit, and irreversible.
            </li>
          </Bullets>
          <p>Here you also set your user password and, if you want, a LUKS2 passphrase. Neither reaches the agent.</p>
          <p>
            An inner virtual machine then installs the system and boots it. Its desktop opens right in the browser:
            launch apps, save files, change settings. Not right? <strong>Revert everything</strong> puts things back as
            they were.
          </p>
        </>
      ),
    },
    {
      id: 'install',
      title: 'Install to your computer',
      summary:
        'Shut the preview down, press Install to computer, choose next to existing data or erase the whole disk. Partitions promoted in place or files copied with checksums. Dual boot not supported yet.',
      content: (
        <>
          <p>
            Shut the preview down from inside, then press <strong>Install to computer</strong>. Choose{' '}
            <em>next to existing data</em> or <em>erase the whole disk</em>, and pick the drive.
          </p>
          <Bullets>
            <li>
              If the preview lived in a partition of the target disk, its partitions become the disk's partitions. No
              data is copied.
            </li>
            <li>
              If it lived in memory or on another drive, files are copied into new partitions and verified with
              checksums.
            </li>
          </Bullets>
          <p>The initramfs is rebuilt for the real hardware and the bootloader is registered.</p>
          <Note label="Read before confirming" tone="warn">
            <p>
              Nothing changes until you confirm here. The install replaces what is on the drive you pick, so back up
              first. Dual boot is not supported yet. If something goes wrong, the installer tells you where it stopped
              and leaves things as they are.
            </p>
          </Note>
        </>
      ),
    },
    {
      id: 'first-boot',
      title: 'First boot',
      summary: 'Remove the USB stick and reboot. First-run check agi-os-verify. GPT, ext4 Btrfs XFS F2FS, GRUB or systemd-boot, LUKS2, zram swap.',
      content: (
        <>
          <p>
            Remove the USB stick and reboot. The installed system opens a first-run check that confirms the boot entry,
            the filesystem and the packages you asked for.
          </p>
          <CommandLine text="agi-os-verify" />
          <p>
            What you get underneath: GPT, a root on ext4, Btrfs, XFS or F2FS, GRUB or systemd-boot, optional LUKS2
            encryption and zram swap.
          </p>
        </>
      ),
    },
  ],
}
