import type { ComponentProps } from 'react'

import { agentMarks, type AgentMark } from '../model/marks'

interface AgentIconProps extends Omit<ComponentProps<'svg'>, 'children'> {
  mark: AgentMark
}

// Нейтральный «штекер» для любых OpenAI-совместимых эндпоинтов (Solar Icons, MIT).
function CompatibleShape() {
  return (
    <g fill="none" stroke="currentColor" strokeWidth="1.5">
      <path
        strokeLinecap="round"
        d="M12 15.1082V20.1498C12 21.2635 11.0955 22.1875 10.0128 21.9673C5.44193 21.0381 2 16.9659 2 12.0832C2 6.51441 6.47715 2 12 2C17.5228 2 22 6.51441 22 12.0832C22 16.0743 19.7003 19.5239 16.3641 21.1581"
      />
      <path
        strokeLinejoin="round"
        d="M9 11.8C9 11.3582 9.35817 11 9.8 11H14.2C14.6418 11 15 11.3582 15 11.8V12C15 13.6569 13.6569 15 12 15C10.3431 15 9 13.6569 9 12V11.8Z"
      />
      <path strokeLinecap="round" d="M13.5 11V9M10.5 11V9" />
    </g>
  )
}

function MarkShape({ mark }: { mark: AgentMark }) {
  return mark === 'compatible' ? <CompatibleShape /> : <path fill="currentColor" d={agentMarks[mark]} />
}

export function AgentIcon({ mark, ...props }: AgentIconProps) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <MarkShape mark={mark} />
    </svg>
  )
}

const symbolId = (mark: AgentMark) => `agent-mark-${mark}`

/**
 * Спрайт контуров для мест, где иконки повторяются много раз (лента агентов): каждый контур
 * попадает в HTML один раз, а копии ссылаются на него через `AgentIconRef`.
 */
export function AgentIconSprite({ marks }: { marks: readonly AgentMark[] }) {
  return (
    <svg aria-hidden="true" width="0" height="0" className="absolute">
      {marks.map((mark) => (
        <symbol key={mark} id={symbolId(mark)} viewBox="0 0 24 24">
          <MarkShape mark={mark} />
        </symbol>
      ))}
    </svg>
  )
}

export function AgentIconRef({ mark, ...props }: AgentIconProps) {
  return (
    <svg aria-hidden="true" {...props}>
      <use href={`#${symbolId(mark)}`} />
    </svg>
  )
}
