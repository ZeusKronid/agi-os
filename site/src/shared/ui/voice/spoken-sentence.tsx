import { cn } from '@/shared/lib/cn'

export interface SpokenWord {
  text: string
  /** Слово-инструмент: курсив, краснеет, когда дослушано. */
  id?: string
}

interface SpokenSentenceProps {
  words: readonly SpokenWord[]
  /** Размер и позиция строки, например `text-xl`. */
  className?: string
  /**
   * Показать фразу уже дослушанной в SSR-разметке (слова видны, инструменты Accent).
   * Нужно там, где фраза — единственная сцена: без JavaScript картинка остаётся законченной. Таймлайн всё равно начинает с пустой строки.
   */
  heard?: boolean
}

/** Фраза, набирающаяся по словам: слова стартуют невидимыми, GSAP проявляет их по мере речи. */
export function SpokenSentence({ words, className, heard = false }: SpokenSentenceProps) {
  return (
    <p className={cn('m-0 flex flex-wrap justify-center gap-x-[.32em] font-serif text-ink', className)}>
      {words.map((word) => (
        <span
          key={word.text}
          data-word=""
          data-tool={word.id}
          data-hit={heard && !!word.id}
          className={cn('transition-colors duration-250 data-[hit=true]:text-accent', !heard && 'opacity-0', word.id && 'italic')}
        >
          {word.text}
        </span>
      ))}
    </p>
  )
}
