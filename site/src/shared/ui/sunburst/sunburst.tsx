import { useId, type ComponentProps } from 'react'

import { ARC_DOTS, buildRays, type SunburstSpec } from './rays'

type SunburstVariant = 'hero' | 'mark' | 'disc'

const specs: Record<SunburstVariant, SunburstSpec> = {
  // Большой восход над заголовком hero.
  hero: {
    width: 640, height: 246, cx: 320, cy: 236, radius: 155, rays: 96, full: false, seed: 7,
    long: 0.37, shortMin: 0.13, shortMax: 0.27, fade: [1.03, 1.46], strokeWidth: 0.9, farDots: true,
  },
  // Маленький восход над заголовком секции.
  mark: {
    width: 240, height: 98, cx: 120, cy: 92, radius: 60, rays: 40, full: false, seed: 3,
    long: 0.37, shortMin: 0.13, shortMax: 0.27, fade: [1.03, 1.46], strokeWidth: 1, farDots: false,
  },
  // Полный диск — приглушённый задник внутри окна демо.
  disc: {
    width: 300, height: 300, cx: 150, cy: 150, radius: 70, rays: 72, full: true, seed: 5,
    long: 0.6, shortMin: 0.2, shortMax: 0.42, fade: [1.05, 1.75], strokeWidth: 1, farDots: false,
  },
}

// Лучи считаются один раз на модуль: чистая детерминированная математика, одинаковая на сервере и клиенте.
const rays = {
  hero: buildRays(specs.hero),
  mark: buildRays(specs.mark),
  disc: buildRays(specs.disc),
} satisfies Record<SunburstVariant, unknown>

interface SunburstProps extends Omit<ComponentProps<'svg'>, 'children'> {
  variant: SunburstVariant
}

/** Знак-восход: тонкая коралловая дуга с лучами. Декоративный, скрыт от ассистивных технологий. */
export function Sunburst({ variant, ...props }: SunburstProps) {
  const spec = specs[variant]
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const fadeId = `sun-fade-${id}`
  const maskId = `sun-mask-${id}`
  const { cx, cy, radius } = spec

  return (
    <svg
      viewBox={`0 0 ${spec.width} ${spec.height}`}
      fill="none"
      stroke="currentColor"
      aria-hidden="true"
      {...props}
    >
      <defs>
        <radialGradient id={fadeId} gradientUnits="userSpaceOnUse" cx={cx} cy={cy} r={radius * spec.fade[1]}>
          <stop offset={(spec.fade[0] / spec.fade[1]).toFixed(2)} stopColor="#fff" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </radialGradient>
        <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width={spec.width} height={spec.height}>
          <rect width={spec.width} height={spec.height} fill={`url(#${fadeId})`} />
        </mask>
      </defs>

      <g mask={`url(#${maskId})`} strokeWidth={spec.strokeWidth}>
        {rays[variant].map((ray, index) => (
          <line key={index} x1={ray.x1} y1={ray.y1} x2={ray.x2} y2={ray.y2} strokeOpacity={ray.opacity} />
        ))}
      </g>

      <g strokeWidth="1.5">
        {spec.full ? (
          <circle cx={cx} cy={cy} r={radius} />
        ) : (
          <path d={`M${cx - radius} ${cy}A${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`} />
        )}
      </g>

      {!spec.full && (
        <g fill="currentColor" stroke="none">
          <line x1={cx} y1={cy - radius} x2={cx} y2={(cy - radius * 0.46).toFixed(1)} stroke="currentColor" strokeWidth="1" />
          <circle cx={cx} cy={(cy - radius * 0.43).toFixed(1)} r="2.2" />
          {ARC_DOTS.map((degrees) => {
            const angle = (degrees * Math.PI) / 180
            return (
              <circle
                key={degrees}
                cx={(cx + radius * Math.cos(angle)).toFixed(1)}
                cy={(cy + radius * Math.sin(angle)).toFixed(1)}
                r={degrees === 180 || degrees === 360 ? 2.4 : 1.6}
              />
            )
          })}
          {spec.farDots && (
            <>
              <circle cx={cx - 282} cy={cy - 108} r="2" />
              <circle cx={cx + 282} cy={cy - 108} r="2" />
            </>
          )}
        </g>
      )}
    </svg>
  )
}
