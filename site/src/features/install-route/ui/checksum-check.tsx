import { useId, useState } from 'react'

import { cn } from '@/shared/lib/cn'

import { compareChecksum } from '../model/checksum'

interface ChecksumCheckProps {
  expected: string
  placeholder: string
  onMatch: () => void
}

/** Поле для вывода `sha256sum`: сверяет вставленный хэш с релизом прямо на странице. */
export function ChecksumCheck({ expected, placeholder, onMatch }: ChecksumCheckProps) {
  const id = useId()
  const [value, setValue] = useState('')
  const result = compareChecksum(value, expected)

  return (
    <div className="grid gap-2">
      <label htmlFor={id} className="font-mono text-[10.5px] tracking-[0.16em] text-ink-muted uppercase">
        Paste the output here to compare
      </label>
      <input
        id={id}
        value={value}
        onChange={(event) => {
          setValue(event.target.value)
          if (compareChecksum(event.target.value, expected) === 'match') onMatch()
        }}
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholder}
        className={cn(
          'h-11 w-full min-w-0 rounded-[10px] bg-elevated px-3 font-mono text-[12.5px] text-ink inset-ring inset-ring-line-strong transition-[box-shadow] duration-200 placeholder:text-ink-dim focus:outline-none focus:inset-ring-accent',
          result === 'match' && 'inset-ring-ok/60',
          result === 'mismatch' && 'inset-ring-accent',
        )}
      />
      <p role="status" className="min-h-0 text-sm">
        {result === 'match' && (
          <span className="flex gap-2 text-ok">
            <span aria-hidden="true" className="mt-[7px] size-1.5 shrink-0 rounded-full bg-ok" />
            Matches the release. Your image is intact.
          </span>
        )}
        {result === 'mismatch' && (
          <span className="flex gap-2 text-ink-soft">
            <span aria-hidden="true" className="mt-[7px] size-1.5 shrink-0 rounded-full bg-accent" />
            Doesn’t match. Download the image again — a partial file or another release gives a different fingerprint.
          </span>
        )}
      </p>
    </div>
  )
}
