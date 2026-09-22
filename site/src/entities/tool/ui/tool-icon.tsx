import type { ComponentProps } from 'react'

import { toolGlyphs, toolMarks } from '../model/marks'
import type { ToolIcon as ToolIconSpec } from '../model/tools'

interface ToolIconProps extends Omit<ComponentProps<'svg'>, 'children'> {
  icon: ToolIconSpec
}

/** Знак инструмента: залитый логотип проекта или контурный глиф для понятий без логотипа. */
export function ToolIcon({ icon, ...props }: ToolIconProps) {
  if ('mark' in icon) {
    return (
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...props}>
        <path d={toolMarks[icon.mark]} />
      </svg>
    )
  }
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d={toolGlyphs[icon.glyph]} />
    </svg>
  )
}
