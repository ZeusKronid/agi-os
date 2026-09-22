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
}

/** Фраза, набирающаяся по словам: слова стартуют невидимыми, GSAP проявляет их по мере речи. */
export function SpokenSentence({ words, className }: SpokenSentenceProps) {
  return (
    <p className={cn('m-0 flex flex-wrap justify-center gap-x-[.32em] font-serif text-ink', className)}>
      {words.map((word) => (
        <span
          key={word.text}
          data-word=""
          data-tool={word.id}
          data-hit="false"
          className={cn('opacity-0 transition-colors duration-250 data-[hit=true]:text-accent', word.id && 'italic')}
        >
          {word.text}
        </span>
      ))}
    </p>
  )
}
