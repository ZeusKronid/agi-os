import { AgentIcon, agents } from '@/entities/agent'

// Набор повторяется столько раз, чтобы половина ленты была заведомо шире любого монитора:
// сдвиг на -50% тогда бесшовен на любой ширине, без измерений в JavaScript.
const REPEATS = 6

function Half() {
  return (
    <ul className="flex shrink-0 gap-16 pr-16 max-sm:gap-11 max-sm:pr-11">
      {Array.from({ length: REPEATS }, (_, repeat) =>
        agents.map((agent) => (
          <li
            key={`${repeat}-${agent.id}`}
            className="grid justify-items-center gap-2.5 whitespace-nowrap opacity-60 transition-opacity duration-200 hover:opacity-100"
          >
            <AgentIcon mark={agent.mark} className="size-[30px]" />
            <span className="text-[12.5px] text-ink-muted">{agent.label}</span>
          </li>
        )),
      )}
    </ul>
  )
}

/**
 * Лента агентов: только иконки с названием, без заголовка и рамок.
 * Крутится всегда — это медленное линейное движение без вспышек, а не вход/выход элементов;
 * остановить его можно наведением или фокусом (пауза), что покрывает требование «дать способ остановить».
 */
export function AgentsMarquee() {
  return (
    <section aria-label="Agents you can connect" className="pt-11 pb-24 max-sm:pt-7 max-sm:pb-16">
      <p className="sr-only">Works with {agents.map((agent) => agent.label).join(', ')}.</p>
      <div aria-hidden="true" className="mask-fade-x overflow-hidden">
        <div className="flex w-max animate-marquee will-change-transform hover:[animation-play-state:paused]">
          <Half />
          <Half />
        </div>
      </div>
    </section>
  )
}
