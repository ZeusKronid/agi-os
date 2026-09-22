import type { ComponentProps } from 'react'

/** Знак AGIOS (Δ G I ◇ S) линиями; цвет наследуется через `currentColor`. */
export function Logo(props: ComponentProps<'svg'>) {
  return (
    <svg viewBox="60 55 1060 250" fill="none" role="img" aria-label="AGIOS" {...props}>
      <g stroke="currentColor" strokeWidth="25" strokeLinecap="square" strokeLinejoin="miter">
        <path d="M90 275 L185 85 L280 275 Z" />
        <path d="M470 90 L330 180 L470 280 L470 190 L415 190" />
        <path d="M565 90 L565 275" />
        <path d="M760 85 L855 180 L760 275 L665 180 Z" />
        <path d="M1080 90 L945 155 L1075 215 L945 280" />
      </g>
    </svg>
  )
}
