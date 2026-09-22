import type { ComponentProps, ReactNode } from 'react'

import { cn } from '@/shared/lib/cn'

/**
 * Типографика статьи документации. Абзацы Geist 16px Ink Soft, подзаголовки антиквой,
 * код моноширинный. Списки и заметки — отдельные компоненты ниже, чтобы стили не расползались.
 */
export function Prose({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'max-w-[66ch] [&>*+*]:mt-[18px]',
        '[&_p]:text-[16px] [&_p]:leading-[1.62] [&_p]:text-ink-soft',
        '[&_strong]:font-medium [&_strong]:text-ink',
        '[&_code]:rounded-[4px] [&_code]:bg-elevated [&_code]:px-[5px] [&_code]:py-[1px] [&_code]:font-mono [&_code]:text-[.9em] [&_code]:text-ink',
        '[&_h3]:mt-7 [&_h3]:font-serif [&_h3]:text-[22px] [&_h3]:tracking-[-0.012em]',
        '[&_a]:underline [&_a]:decoration-line-accent [&_a]:underline-offset-4 [&_a]:transition-colors [&_a]:hover:text-ink [&_a]:hover:decoration-accent',
        className,
      )}
      {...props}
    />
  )
}

/** Маркированный список: коралловая точка вместо стандартного маркера. */
export function Bullets({ className, ...props }: ComponentProps<'ul'>) {
  return (
    <ul
      className={cn(
        'grid gap-2 [&>li]:relative [&>li]:pl-[18px] [&>li]:text-[16px] [&>li]:leading-[1.62] [&>li]:text-ink-soft',
        '[&>li]:before:absolute [&>li]:before:top-[.72em] [&>li]:before:left-0 [&>li]:before:size-[5px] [&>li]:before:rounded-full [&>li]:before:bg-accent',
        className,
      )}
      {...props}
    />
  )
}

/** Нумерованный список шагов: номер моноширинный, коралловый, с ведущим нулём. */
export function Steps({ className, ...props }: ComponentProps<'ol'>) {
  return (
    <ol
      className={cn(
        'grid gap-2.5 [counter-reset:step] [&>li]:relative [&>li]:pl-[34px] [&>li]:text-[16px] [&>li]:leading-[1.62] [&>li]:text-ink-soft [&>li]:[counter-increment:step]',
        '[&>li]:before:absolute [&>li]:before:top-[.32em] [&>li]:before:left-0 [&>li]:before:font-mono [&>li]:before:text-[11px] [&>li]:before:tracking-[0.1em] [&>li]:before:text-accent [&>li]:before:content-[counter(step,decimal-leading-zero)]',
        className,
      )}
      {...props}
    />
  )
}

interface NoteProps {
  label: string
  /** `warn` — коралловая рамка для предупреждений перед необратимыми действиями. */
  tone?: 'plain' | 'warn'
  children: ReactNode
}

/** Заметка: карточка Surface с моноширинным лейблом капсом. */
export function Note({ label, tone = 'plain', children }: NoteProps) {
  return (
    <aside
      className={cn(
        'rounded-xl bg-surface px-[18px] py-4 inset-ring inset-ring-line [&_p]:text-[14.5px]',
        tone === 'warn' && 'inset-ring-line-accent',
      )}
    >
      <p className="mb-1.5 font-mono text-[10.5px] tracking-[0.2em] text-accent uppercase">{label}</p>
      {children}
    </aside>
  )
}

interface DocTableProps {
  head: readonly string[]
  rows: readonly (readonly ReactNode[])[]
}

/** Таблица: заголовки моноширинным капсом, первая колонка — Ink, разделители Line. */
export function DocTable({ head, rows }: DocTableProps) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[14.5px]">
        <thead>
          <tr>
            {head.map((cell) => (
              <th
                key={cell}
                scope="col"
                className="border-b border-line pr-3 pb-2.5 text-left font-mono text-[10.5px] font-normal tracking-[0.2em] text-ink-muted uppercase"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  className={cn(
                    'border-b border-line py-[11px] pr-3 align-top text-ink-soft',
                    cellIndex === 0 && 'whitespace-nowrap text-ink',
                  )}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
