import { siteConfig } from '@/shared/config'
import { CommandLine } from '@/shared/ui/command-line'

import { Bullets, DocTable, Note, Steps } from '../../ui/prose'
import type { DocPage } from '../types'

// Факты — из README и docs/local-web.md: что подтверждено прогонами в VM, что пока экспериментально.
export const gettingStarted: DocPage = {
  slug: 'getting-started',
  chapter: 'start',
  short: 'Overview',
  title: 'Getting',
  em: 'started.',
  lede: 'An Arch Linux installer you talk to. Describe the system you want, try it in your browser, then install it. Nothing touches the disk until you say so.',
  metaTitle: 'Get Started with AGI OS: Boot, Describe, Preview, Install',
  sections: [
    {
      id: 'what-is',
      title: 'What is AGIOS',
      summary:
        'AGIOS, from the Greek hagios, holy: an Arch Linux distribution with an installer you talk to. Official repositories core and extra. Apache 2.0.',
      content: (
        <>
          <p>
            <strong>AGIOS</strong> (from <em className="font-serif text-[1.05em] text-ink not-italic">ἅγιος</em>,
            hágios, Greek for &ldquo;holy&rdquo;) is an Arch Linux distribution with an installer you talk to. You
            describe the system you want, try it in your browser, and install it only when you like what you see.
          </p>
          <p>
            Software comes from the official Arch repositories, <code>core</code> and <code>extra</code>. The project
            is open source under the Apache&nbsp;2.0 license.
          </p>
        </>
      ),
    },
    {
      id: 'why',
      title: 'Why AGIOS',
      summary:
        'Talk, do not configure. Try before you install. Undo by default. Bring your own model: ChatGPT, OpenAI, Anthropic, Gemini, Ollama, OpenAI-compatible.',
      content: (
        <Bullets>
          <li>
            <strong>Talk, don&apos;t configure.</strong> An agent picks the desktop, packages and settings from the
            official Arch repositories; the installer validates every proposal against the real package catalog and
            your hardware.
          </li>
          <li>
            <strong>Try before you install.</strong> The system is built in a VM inside the Live session and shown
            right in the browser. Use it, ask for changes, rebuild.
          </li>
          <li>
            <strong>Undo by default.</strong> The preview lives in RAM, in a file on a USB stick or in a temporary
            partition, each with its own rollback. Disks change only after an explicit, typed confirmation.
          </li>
          <li>
            <strong>Bring your own model.</strong> ChatGPT sign-in, OpenAI, Anthropic, Gemini, Ollama on your network,
            or any OpenAI-compatible API. Passwords never reach the model.
          </li>
        </Bullets>
      ),
    },
    {
      id: 'how',
      title: 'How it works',
      summary: 'Boot the Live ISO, Firefox opens localhost:8787. Talk, place, preview, install.',
      content: (
        <>
          <p>
            Boot the Live ISO, and Firefox opens the workspace at <code>localhost:8787</code>. Then four steps:
          </p>
          <Steps>
            <li>
              <strong>Talk.</strong> Describe how you use the computer. The agent asks what it needs and proposes a
              configuration.
            </li>
            <li>
              <strong>Place.</strong> AGIOS measures the exact system size and lists where the preview can live, each
              with its undo.
            </li>
            <li>
              <strong>Preview.</strong> The installed system boots in a VM and streams into the page through Apache
              Guacamole.
            </li>
            <li>
              <strong>Install.</strong> Keep it or put everything back. Installing promotes or copies the checked
              system to your disk.
            </li>
          </Steps>
        </>
      ),
    },
    {
      id: 'requirements',
      title: 'Before you begin',
      summary:
        'A 64-bit PC, UEFI or BIOS, Secure Boot off for the Live ISO. Tested in virtual machines, real hardware experimental. USB stick or VM. A model. A backup.',
      content: (
        <Bullets>
          <li>
            A 64-bit PC with UEFI or BIOS. The Live ISO is not signed, so boot it with Secure Boot off. AGIOS is tested
            in virtual machines; real hardware is still experimental, so start with a spare machine.
          </li>
          <li>A USB stick or a virtual machine to boot the ISO from. The image is about 2&nbsp;GB.</li>
          <li>
            A model to connect: a ChatGPT account, an API key from OpenAI, Anthropic or Gemini, Ollama on your network,
            or any OpenAI-compatible endpoint.
          </li>
          <li>A backup of anything you care about on the target drive.</li>
        </Bullets>
      ),
    },
  ],
}

export const stepByStep: DocPage = {
  slug: 'step-by-step',
  chapter: 'start',
  short: 'Step by step',
  title: 'Install,',
  em: 'step by step.',
  lede: 'From a downloaded ISO to a system that is yours. Nothing on your disk changes until you confirm the install yourself.',
  metaTitle: 'Install AGI OS Step by Step: Boot, Describe, Preview, Install',
  metaDescription:
    'Boot the AGIOS Live ISO, connect a model, describe the system, try it in a live preview and install it next to your other systems or on an erased disk.',
  sections: [
    {
      id: 'boot',
      title: 'Boot the ISO',
      summary:
        'Download and verify the image, write it to a USB stick or attach it to a VM, boot. Firefox opens the workspace at localhost:8787. Passwordless sudo in the Live session.',
      content: (
        <>
          <p>
            <a href={siteConfig.links.install}>Download and verify the image</a>, write it to a USB stick or attach it
            to a virtual machine, and boot. Firefox opens the workspace by itself. At this point nothing on your disk
            has changed.
          </p>
          <CommandLine text="http://localhost:8787" />
          <Note label="Tip">
            <p>
              In the Live session the desktop user <code>agi</code> has passwordless sudo:{' '}
              <code>sudo pacman -S &lt;package&gt;</code> works for the session and is gone after reboot.
            </p>
          </Note>
        </>
      ),
    },
    {
      id: 'connect',
      title: 'Connect your model',
      summary:
        'ChatGPT sign-in, OpenAI, Anthropic or Gemini API key, Ollama on your network, OpenAI-compatible endpoint. Keys stay in memory for the session.',
      content: (
        <>
          <p>Choose how the agent signs in. Nothing is bundled: you bring the model you already use.</p>
          <DocTable
            head={['Model', 'Way in']}
            rows={[
              ['ChatGPT', 'Sign in with your account'],
              ['OpenAI API', 'API key'],
              ['Anthropic', 'API key'],
              ['Gemini', 'API key'],
              ['Ollama', 'A server on your network'],
              ['Compatible endpoint', 'Any OpenAI-compatible URL'],
            ]}
          />
          <Note label="Privacy">
            <p>
              Keys stay in the app&apos;s memory for the session. They are never sent into the chat and never copied to
              the installed system. Your provider may charge for API usage.
            </p>
          </Note>
        </>
      ),
    },
    {
      id: 'talk',
      title: 'Talk',
      summary:
        'Describe how you use the computer: desktop or window manager, theme, tools, languages, keyboard layouts. Choose for me gives the standard XFCE system. Checked against the catalog and your hardware.',
      content: (
        <>
          <p>
            Describe how you use the computer: a desktop or a window manager, a theme, tools, languages, keyboard
            layouts, or no desktop at all. The agent asks what it needs and proposes a configuration; the app checks it
            against the package catalog and your hardware before anything is built.
          </p>
          <p>
            Don&apos;t want to choose? <strong>Choose for me</strong> gives the standard system: XFCE with LightDM,
            Firefox and NetworkManager on ext4. The agent then asks only for your name, language, layouts, time zone
            and the disk.
          </p>
          <Note label="Example">
            <p>&ldquo;Hyprland, dark theme, neovim, docker and waybar.&rdquo;</p>
          </Note>
        </>
      ),
    },
    {
      id: 'place',
      title: 'Place',
      summary:
        'Find room for the preview: exact size from package data. RAM, file on a drive, new partition, shrink NTFS or ext4, erase the disk. User password, LUKS2 passphrase, Secure Boot.',
      content: (
        <>
          <p>
            Press <strong>All set — find room for the preview</strong>. AGIOS measures the exact system size from package data
            and lists where the preview can live: RAM, a file on any drive, a new partition, a shrunk NTFS or ext4
            partition, or the erased target disk. Each option shows what it touches and how to undo it; see{' '}
            <a href="/docs/preview-placement">where the preview lives</a>.
          </p>
          <p>
            Then set your user password and, if you want, a LUKS2 passphrase, and press{' '}
            <strong>Build the preview</strong>. Neither password reaches the model. On UEFI with systemd-boot you can
            also sign the system for Secure Boot with its own keys.
          </p>
        </>
      ),
    },
    {
      id: 'preview',
      title: 'Preview',
      summary:
        'The installed system boots in a VM and streams into the page through Apache Guacamole. Use it, ask for changes, rebuild, or put everything back.',
      content: (
        <p>
          An inner virtual machine installs the system and boots it. Its desktop streams into the page through Apache
          Guacamole: launch apps, save files, change settings. Ask for changes and rebuild. Not right?{' '}
          <strong>Put everything back</strong> undoes the storage.
        </p>
      ),
    },
    {
      id: 'install',
      title: 'Install',
      summary:
        'Turn the preview off, press Install, keep what is on the disk or erase the disk, type the disk path. Promote in place or copy with checksums. Drivers, initramfs, bootloader. Dual boot.',
      content: (
        <>
          <p>
            Press <strong>Install</strong>; AGIOS first turns the preview off like a computer. Choose{' '}
            <em>keep what&apos;s on the disk</em> to install next to your files and other systems, or{' '}
            <em>erase the disk</em>. Then type the disk path to confirm.
          </p>
          <Bullets>
            <li>
              A preview partition on the target disk is <strong>promoted</strong>: it becomes the system in place, no
              data moves.
            </li>
            <li>
              Any other preview is <strong>copied</strong> into fresh partitions and verified by checksum.
            </li>
          </Bullets>
          <p>
            Missing hardware drivers are added for the real computer, the initramfs is rebuilt and the bootloader is
            registered in firmware.
          </p>
          <Note label="Read before confirming" tone="warn">
            <p>
              Nothing changes until you confirm here, so back up first. Next to Windows, shut it down fully: a
              hibernated Windows (Fast Startup included) stops the install before anything is written. If something
              goes wrong, the installer tells you where it stopped and leaves things as they are.
            </p>
          </Note>
        </>
      ),
    },
    {
      id: 'first-boot',
      title: 'First boot',
      summary:
        'Remove the USB stick and reboot. The first-boot check agi-os-verify confirms the boot entry, filesystem and packages.',
      content: (
        <>
          <p>
            Remove the stick and reboot. The first-boot check opens in the new system and confirms the boot entry, the
            filesystem and the packages you asked for.
          </p>
          <CommandLine text="agi-os-verify" />
          <p>
            What the system is made of is listed in <a href="/docs/disks-and-boot">install targets</a>.
          </p>
        </>
      ),
    },
  ],
}
