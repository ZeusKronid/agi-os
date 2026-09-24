import { spokenSentence } from '@/entities/tool'
import { cn } from '@/shared/lib/cn'
import { MicButton, SpokenSentence, Wave } from '@/shared/ui/voice'

import { mountWordsVisual } from '../lib/mount-words-visual'

const WAVE_BARS = 84

const label = 'font-mono text-[10.5px] tracking-[0.16em] text-ink-muted uppercase'

/**
 * Визуал карточки «Say it in words»: одна сцена «слушаю», по кругу.
 * Волна разбегается слева направо, участки речи краснеют, фраза набирается по словам; потом волна схлопывается и всё начинается заново.
 * Подпись-состояние: `listening` (точка мигает) → `got it`. SSR-разметка показывает фразу дослушанной; таймлайн живёт в `mountWordsVisual`.
 */
export function WordsVisual() {
  return (
    <div ref={mountWordsVisual} className="absolute inset-0">
      <span data-label="" data-state="heard" className={cn(label, 'group/label absolute top-3.5 left-[18px] z-10 flex items-center gap-2')}>
        <i className="size-1.5 animate-blink rounded-full bg-accent group-data-[state=heard]/label:hidden" />
        <span className="group-data-[state=heard]/label:hidden">listening</span>
        <span className="group-data-[state=listening]/label:hidden">got it</span>
      </span>

      <MicButton className="absolute top-1/2 left-4 z-10 size-7 -translate-y-1/2 max-sm:top-3 max-sm:right-3 max-sm:left-auto max-sm:translate-y-0" />
      <Wave
        bars={WAVE_BARS}
        className="absolute top-[44%] right-[18px] left-[58px] h-16 -translate-y-1/2 max-sm:top-[40%] max-sm:right-3 max-sm:left-3"
      />
      <SpokenSentence
        heard
        words={spokenSentence}
        className="absolute inset-x-6 bottom-[22px] text-xl leading-[1.3] tracking-[-0.012em] max-sm:inset-x-3 max-sm:bottom-4 max-sm:text-[17px]"
      />
    </div>
  )
}
