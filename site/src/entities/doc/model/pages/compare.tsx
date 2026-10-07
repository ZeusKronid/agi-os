import { Bullets, DocTable, Note } from '../../ui/prose'
import type { DocPage } from '../types'

// Сравнение для поиска «archinstall alternative». Про archinstall — только проверяемое: README проекта
// (github.com/archlinux/archinstall) и заметки к релизам 3.x; про AGI OS — те же факты, что в остальных доках.
export const vsArchinstall: DocPage = {
  slug: 'vs-archinstall',
  chapter: 'more',
  short: 'AGI OS vs archinstall',
  title: 'AGI OS and',
  em: 'archinstall.',
  lede: 'Both install Arch Linux from the official repositories. archinstall asks you to pick options from menus; AGI OS lets you describe the system and try it before it touches your disk.',
  metaTitle: 'AGI OS vs archinstall — an Arch Installer You Can Talk To',
  metaDescription:
    'How AGI OS compares to archinstall, the official Arch Linux guided installer: menus versus plain words, a live preview before install, desktop setup, disks and current limits.',
  sections: [
    {
      id: 'short',
      title: 'The short answer',
      summary:
        'archinstall: official menu-driven installer on the Arch ISO, profiles, JSON configs, no AI. AGI OS: describe the system in words, an agent builds it, you try it in a live preview, then it moves to your disk.',
      content: (
        <>
          <p>
            <strong>archinstall</strong> is the official guided installer that ships on the Arch Linux ISO. You walk
            through terminal menus, pick a disk layout, a bootloader and a profile such as GNOME, KDE Plasma or
            Hyprland, and it installs that profile&apos;s packages. Everything after that is up to you.
          </p>
          <p>
            <strong>AGI OS</strong> is a live ISO with an agent inside. You say what you want, for example
            &ldquo;Hyprland, dark theme, neovim and Docker&rdquo;. The agent picks packages from the same official
            repositories and writes the configuration. You click around the result in a live preview, and the exact
            system you tried moves to your computer.
          </p>
        </>
      ),
    },
    {
      id: 'table',
      title: 'Side by side',
      summary:
        'Interface, desktop setup, preview before install, AI requirement, maturity and dual boot compared.',
      content: (
        <DocTable
          head={['', 'archinstall', 'AGI OS']}
          rows={[
            ['How you choose', 'Terminal menus and profiles', 'Plain words in a chat'],
            ['Desktop setup', 'Default packages of the profile', 'Themes, bars, tools and configs you ask for'],
            ['See it before installing', 'No', 'Yes, the real system in a live preview'],
            ['Needs a model', 'No', 'Yes: ChatGPT, an API key or a local Ollama model'],
            ['Maturity', 'Official, widely used', 'Early: tested in VMs, real hardware experimental'],
            ['Dual boot', 'Possible with manual partitioning', 'Not yet'],
          ]}
        />
      ),
    },
    {
      id: 'when-archinstall',
      title: 'When archinstall is the better choice',
      summary:
        'You want the official tool, already know which profile you need, need dual boot, want unattended installs from a JSON file, or do not want any AI in the loop.',
      content: (
        <Bullets>
          <li>You want the official tool and already know which profile you need.</li>
          <li>You need dual boot or want to keep existing partitions.</li>
          <li>You install many machines unattended from one JSON file.</li>
          <li>You do not want a model involved at all.</li>
        </Bullets>
      ),
    },
    {
      id: 'when-agios',
      title: 'When AGI OS is the better choice',
      summary:
        'You want a configured desktop, not just a base system; you want to try it before committing; you know what you want but not every package and config file behind it.',
      content: (
        <>
          <Bullets>
            <li>You want a configured desktop, not a base system you rice for an evening.</li>
            <li>You want to try the system before anything is written to your disk.</li>
            <li>You know what you want, but not every package and config file behind it.</li>
          </Bullets>
          <Note label="Same Arch">
            <p>
              Both end in a regular Arch Linux system from the official repositories. AGI OS does not add its own
              package repository, and the installed system updates with pacman like any other Arch install.
            </p>
          </Note>
        </>
      ),
    },
  ],
}
