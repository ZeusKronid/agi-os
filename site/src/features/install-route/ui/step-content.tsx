import type { ReactNode } from 'react'

import { isoCommandName, isoDisplayName, release } from '@/entities/release'
import { ButtonLink } from '@/shared/ui/button'
import { CommandLine } from '@/shared/ui/command-line'
import { ArrowDownIcon } from '@/shared/ui/icon'

import {
  findCommand,
  type OsId,
  type StepId,
  type TargetId,
  verifyCommand,
  vmCommands,
  writeCommands,
} from '../model/route'
import { ChecksumCheck } from './checksum-check'

const file = isoCommandName(release)

/** Предупреждение перед необратимым действием — коралловая линия, как `Note tone="warn"` в docs. */
function Warn({ children }: { children: ReactNode }) {
  return (
    <p className="flex gap-2.5 rounded-[10px] bg-surface px-3.5 py-2.5 text-sm text-ink-soft inset-ring inset-ring-line-accent">
      <span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-accent" />
      <span>{children}</span>
    </p>
  )
}

const Code = ({ children }: { children: ReactNode }) => (
  <code className="rounded bg-elevated px-1.5 py-0.5 font-mono text-[0.88em] text-ink">{children}</code>
)

interface StepContentProps {
  step: StepId
  os: OsId
  target: TargetId
  onDone: () => void
}

export function StepContent({ step, os, target, onDone }: StepContentProps) {
  switch (step) {
    case 'download':
      return (
        <>
          <p>
            <span className="font-mono text-ink">{isoDisplayName(release)}</span> · x86_64 · {release.size}
          </p>
          <div>
            <ButtonLink href={release.isoUrl} size="sm" onClick={onDone}>
              Download ISO <ArrowDownIcon />
            </ButtonLink>
          </div>
          {release.version === null && (
            <p className="text-sm text-ink-muted">
              The release page with the image and its checksum is on its way. Until then the button opens the repository.
            </p>
          )}
        </>
      )

    case 'verify':
      return (
        <>
          <CommandLine text={verifyCommand(os, file)} />
          {release.sha256 ? (
            <ChecksumCheck expected={release.sha256} placeholder={`${release.sha256.slice(0, 8)}…  ${file}`} onMatch={onDone} />
          ) : (
            <p>
              Compare the result with the SHA-256 on the release page. If they differ, download again — a partial file
              won’t boot cleanly.
            </p>
          )}
        </>
      )

    case 'find':
      if (os === 'win') return null
      return (
        <>
          <CommandLine text={findCommand(os)} />
          <p>
            Plug the stick in and note its name — {os === 'mac' ? <Code>disk4</Code> : <Code>sdb</Code>}, for example.
            Size and model help you tell it apart.
          </p>
        </>
      )

    case 'write':
      if (os === 'win') {
        return (
          <>
            <p>
              Open <strong className="font-medium text-ink">Rufus</strong>, pick your stick and the ISO, press Start. When
              Rufus asks, choose <strong className="font-medium text-ink">Write in DD Image mode</strong>. balenaEtcher
              works too.
            </p>
            <Warn>Everything on the stick is erased.</Warn>
          </>
        )
      }
      return (
        <>
          {writeCommands(os, file).map((command) => (
            <CommandLine key={command} text={command} />
          ))}
          <Warn>
            Replace <Code>{os === 'mac' ? 'diskN' : 'sdX'}</Code> with your stick. Everything on that device is erased.
          </Warn>
        </>
      )

    case 'vm':
      return (
        <>
          {vmCommands(file).map((command) => (
            <CommandLine key={command} text={command} />
          ))}
          <p>
            UEFI, 10 GB of memory, 6 vCPUs and a 20 GB disk — the setup AGI OS is tested with. The live preview starts a
            virtual machine of its own, so pass the host CPU through.
          </p>
          {os === 'mac' && (
            <Warn>
              On Apple silicon this needs x86_64 emulation. It will be slow and isn’t tested — a Linux or Windows PC is a
              better host.
            </Warn>
          )}
          {os === 'win' && (
            <p className="text-sm text-ink-muted">
              On Windows, use any hypervisor with UEFI firmware and nested virtualization. Only QEMU/KVM is tested.
            </p>
          )}
        </>
      )

    case 'boot':
      if (target === 'vm') {
        return (
          <p>
            Start the virtual machine. Firefox opens the installer at <Code>localhost:8787</Code> inside the Live system.
            Nothing on your disk has changed.
          </p>
        )
      }
      return (
        <>
          {os === 'mac' && <Warn>Apple silicon Macs can’t boot an x86_64 image. Plug the stick into a 64-bit PC.</Warn>}
          <p>
            Restart and press the boot-menu key — often F12, F11, F9 or Esc. Pick the stick marked UEFI. Firefox opens the
            installer at <Code>localhost:8787</Code> by itself.
          </p>
        </>
      )
  }
}
