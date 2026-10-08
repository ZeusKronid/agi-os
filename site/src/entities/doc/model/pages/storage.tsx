import { CommandLine } from '@/shared/ui/command-line'

import { Bullets, DocTable, Note } from '../../ui/prose'
import type { DocPage } from '../types'

// Факты — из README («Where the preview lives», «Supported install targets») и раздела Limits в docs/local-web.md.
export const previewPlacement: DocPage = {
  slug: 'preview-placement',
  chapter: 'storage',
  short: 'Preview placement',
  title: 'Where the preview',
  em: 'lives.',
  lede: 'Five places, from untouched disks to an erased one. AGIOS measures the exact size first and recommends what fits.',
  metaTitle: 'Where the Live Preview Is Stored — AGI OS Docs',
  sections: [
    {
      id: 'options',
      title: 'The five options',
      summary:
        'RAM compressed zram image, no disks, stop the VM. File on any drive, delete the file. New partition in unallocated space, remove the entry. Shrink NTFS ext4 dry run, restore the boundary. Erase the target disk, irreversible.',
      content: (
        <>
          <DocTable
            head={['Option', 'Touches your disks', 'Undo']}
            rows={[
              ['RAM (zram)', 'No', 'Stop the VM'],
              ['File on any drive', 'Writes one file', 'Delete the file'],
              ['New partition', 'Adds one partition entry', 'Remove the entry'],
              ['Shrink NTFS / ext4', 'Moves a partition boundary', 'Restore the boundary, grow the filesystem'],
              ['Erase the target disk', 'Yes', 'Irreversible'],
            ]}
          />
          <p>
            RAM holds a compressed zram image. The file can go on a USB stick, a second disk or an SD card. A new
            partition takes unallocated space. Shrinking runs a dry run first.
          </p>
        </>
      ),
    },
    {
      id: 'which',
      title: 'Which one is offered',
      summary: 'Non-destructive options that fit come first. RAM needs enough free memory and is watched during the build. Shrinking and erasing need a typed confirmation.',
      content: (
        <Bullets>
          <li>Options that leave your disks as they are and fit the measured size are recommended first.</li>
          <li>RAM needs enough free memory next to the preview VM, and is watched during the build so it stops cleanly instead of failing midway.</li>
          <li>Shrinking and erasing each need a separate, typed confirmation.</li>
        </Bullets>
      ),
    },
    {
      id: 'promote-or-copy',
      title: 'Promote or copy',
      summary:
        'A preview partition on the target disk becomes the system without copying. Any other preview is copied and verified by checksum.',
      content: (
        <p>
          A preview partition on the target disk becomes the system in place, without copying. Any other preview is
          copied into fresh partitions and verified by checksum.
        </p>
      ),
    },
  ],
}

export const disksAndBoot: DocPage = {
  slug: 'disks-and-boot',
  chapter: 'storage',
  short: 'Install targets',
  title: 'Supported install',
  em: 'targets.',
  lede: 'What the installed system is made of, how it lives next to other systems, and the current limits.',
  metaTitle: 'Disks, Boot and Encryption — AGI OS Docs',
  metaDescription:
    'Filesystems, partition tables, bootloaders and encryption AGIOS installs: ext4, Btrfs, XFS, F2FS, GPT or MBR, GRUB or systemd-boot, Secure Boot, LUKS2, zram and hibernation.',
  sections: [
    {
      id: 'supported',
      title: 'Supported',
      summary:
        'ext4 Btrfs XFS F2FS. GPT, or MBR msdos with GRUB on BIOS. GRUB BIOS UEFI, systemd-boot UEFI, Secure Boot with your own keys. LUKS2, zram swap, hibernation via swap file not on F2FS.',
      content: (
        <Bullets>
          <li>Filesystems: ext4, Btrfs, XFS, F2FS.</li>
          <li>Partition tables: GPT, or MBR (msdos) with GRUB on BIOS.</li>
          <li>
            Bootloaders: GRUB (BIOS/UEFI) or systemd-boot (UEFI), optionally signed for Secure Boot with your own keys.
          </li>
          <li>LUKS2 root encryption, zram swap, optional hibernation via a swap file (not on F2FS).</li>
        </Bullets>
      ),
    },
    {
      id: 'alongside',
      title: 'Alongside other systems',
      summary:
        'Dual boot. A preview partition on the target disk becomes the system without copying; other previews are copied and verified. On MBR two free primary entries. Windows stays in the boot menu.',
      content: (
        <>
          <Bullets>
            <li>
              A preview partition on the target disk becomes the system without copying; any other preview is copied
              and verified by checksum.
            </li>
            <li>On MBR this needs two free primary entries.</li>
            <li>
              On UEFI the disk&apos;s existing EFI partition is shared, never formatted, and Windows Boot Manager stays
              in the boot menu. On BIOS, GRUB gets a chainload entry for Windows.
            </li>
          </Bullets>
          <Note label="Windows" tone="warn">
            <p>
              Shut Windows down fully: a hibernated Windows, Fast Startup included, stops the install before anything
              is written. BitLocker volumes are never shrunk.
            </p>
          </Note>
        </>
      ),
    },
    {
      id: 'secure-boot',
      title: 'Secure Boot',
      summary:
        'systemd-boot only: sbctl creates the system own keys and signs the bootloader and kernel. Keys can be enrolled in Setup Mode. The Live ISO is not signed, boot it with Secure Boot off.',
      content: (
        <>
          <p>
            With systemd-boot on UEFI the system gets its own keys: the bootloader and kernel are signed and re-signed
            on every update. The keys can be enrolled in firmware when it is in Setup Mode, together with
            Microsoft&apos;s, so Windows keeps booting. GRUB installs are not signed.
          </p>
          <p>The Live ISO itself is not signed: boot it with Secure Boot off or in Setup Mode.</p>
        </>
      ),
    },
    {
      id: 'first-boot',
      title: 'After installing',
      summary: 'Remove the stick and reboot. The first-boot check agi-os-verify opens in the new system.',
      content: (
        <>
          <p>Remove the stick and reboot. The first-boot check opens in the new system.</p>
          <CommandLine text="agi-os-verify" />
        </>
      ),
    },
    {
      id: 'limits',
      title: 'Current limits',
      summary:
        'Real hardware experimental, tested in QEMU/KVM. Shrinking NTFS and ext4 only. No preview partition and no logical partitions on MBR disks. Hibernation not on F2FS.',
      content: (
        <Bullets>
          <li>Tested in QEMU/KVM virtual machines; runs on physical hardware are still pending.</li>
          <li>Shrinking works for NTFS and ext4 only.</li>
          <li>
            On an MBR disk the preview lives in RAM or on another drive, and no logical partitions are created.
          </li>
          <li>Hibernation is not available on F2FS.</li>
        </Bullets>
      ),
    },
  ],
}
