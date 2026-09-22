import { Bullets, DocTable } from '../../ui/prose'
import type { DocPage } from '../types'

export const previewPlacement: DocPage = {
  slug: 'preview-placement',
  chapter: 'storage',
  short: 'Preview placement',
  title: 'Where the preview',
  em: 'lives.',
  lede: 'Five places, from safest to permanent. The installer proposes one after measuring the exact size.',
  sections: [
    {
      id: 'options',
      title: 'The five options',
      summary: 'Memory zram no disks reboot. File on a drive delete the file. New partition delete the entry. Shrink NTFS ext4 restore the boundary. Erase disk now no undo.',
      content: (
        <DocTable
          head={['Place', 'Touches disks', 'Undo']}
          rows={[
            ['Memory (zram)', 'No', 'Reboot'],
            ['File on a drive', 'One file', 'Delete the file'],
            ['New partition', 'One entry', 'Delete the entry'],
            ['Shrink NTFS / ext4', 'Partition boundary', 'Restore the boundary'],
            ['Erase disk now', 'Everything', 'None'],
          ]}
        />
      ),
    },
    {
      id: 'promote-or-copy',
      title: 'Promote or copy',
      summary: 'A preview in a partition of the target disk is promoted in place. Any other preview is copied file by file with checksum verification.',
      content: (
        <p>
          A preview in a partition of the target disk is promoted in place. Any other preview is copied file by file
          into new partitions with checksum verification.
        </p>
      ),
    },
  ],
}

export const disksAndBoot: DocPage = {
  slug: 'disks-and-boot',
  chapter: 'storage',
  short: 'Disks & boot',
  title: 'Disks, boot and',
  em: 'encryption.',
  lede: 'What the installed system is made of, and what is not supported yet.',
  sections: [
    {
      id: 'supported',
      title: 'Supported',
      summary: 'ext4 Btrfs XFS F2FS. GPT. GRUB BIOS or UEFI, systemd-boot UEFI. LUKS2 root encryption, zram swap.',
      content: (
        <Bullets>
          <li>Filesystems: ext4, Btrfs, XFS, F2FS.</li>
          <li>Partition table: GPT.</li>
          <li>Bootloader: GRUB (BIOS or UEFI) or systemd-boot (UEFI).</li>
          <li>Root encryption with LUKS2; swap on zram.</li>
        </Bullets>
      ),
    },
    {
      id: 'not-yet',
      title: 'Not yet',
      summary: 'Keeping partitions on MBR disks, erase only. Hibernation. Dual boot with another operating system.',
      content: (
        <Bullets>
          <li>Keeping partitions on MBR disks (erase only).</li>
          <li>Hibernation.</li>
          <li>Dual boot with another operating system.</li>
        </Bullets>
      ),
    },
  ],
}
