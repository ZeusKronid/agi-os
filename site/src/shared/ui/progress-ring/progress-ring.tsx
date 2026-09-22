import { cn } from '@/shared/lib/cn'

const TICKS = 24

/**
 * Кольцо «думает → готово»: деления Ink Dim, дорожка Line Strong, прогресс Accent (dasharray 201),
 * поверх — галочка (dasharray 34). Всё состояние ведёт GSAP через `data-ring/progress/tick/check`.
 * Размер задаёт `className` (например `size-[76px]`).
 */
export function ProgressRing({ className }: { className?: string }) {
  return (
    <div className={cn('relative', className)}>
      <svg data-ring="" viewBox="0 0 72 72" aria-hidden="true" className="absolute inset-0 size-full will-change-transform">
        {Array.from({ length: TICKS }, (_, index) => {
          const angle = (index / TICKS) * Math.PI * 2
          const outer = 26
          const inner = index % 6 === 0 ? 22 : 24
          return (
            <line
              key={index}
              data-tick=""
              x1={(36 + Math.cos(angle) * outer).toFixed(1)}
              y1={(36 + Math.sin(angle) * outer).toFixed(1)}
              x2={(36 + Math.cos(angle) * inner).toFixed(1)}
              y2={(36 + Math.sin(angle) * inner).toFixed(1)}
              className="stroke-ink-dim stroke-[1.5]"
            />
          )
        })}
        <circle cx="36" cy="36" r="32" className="fill-none stroke-line-strong stroke-2" />
        <circle
          data-progress=""
          cx="36"
          cy="36"
          r="32"
          className="fill-none stroke-accent stroke-2 [stroke-dasharray:201] [stroke-dashoffset:201] [stroke-linecap:round]"
        />
      </svg>
      <svg data-check="" viewBox="0 0 72 72" aria-hidden="true" className="absolute inset-0 size-full will-change-[transform,opacity]">
        <path
          d="M25 37.5l7.5 7.5 14.5-16"
          className="fill-none stroke-accent stroke-[2.6] [stroke-dasharray:34] [stroke-dashoffset:34] [stroke-linecap:round] [stroke-linejoin:round]"
        />
      </svg>
    </div>
  )
}
