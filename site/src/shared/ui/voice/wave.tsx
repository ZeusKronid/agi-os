import { cn } from '@/shared/lib/cn'

interface WaveProps {
  bars: number
  /** Высота и раскладка дорожки, например `h-16 flex-1`. */
  className?: string
}

/**
 * Волна из столбиков Ink Dim; участки речи получают `data-hit="true"` и краснеют.
 * Высота столбиков начинается со `scaleY(.04)` и анимируется GSAP. На мобильном каждый второй столбик скрыт.
 */
export function Wave({ bars, className }: WaveProps) {
  return (
    <div data-wave="" className={cn('flex items-center gap-[3px] max-sm:gap-0.5 max-sm:[&>i:nth-child(even)]:hidden', className)}>
      {Array.from({ length: bars }, (_, index) => (
        <i
          key={index}
          data-hit="false"
          className="h-full min-w-0.5 flex-1 rounded-sm bg-ink-dim [transform:scaleY(.04)] transition-colors duration-250 data-[hit=true]:bg-accent"
        />
      ))}
    </div>
  )
}
