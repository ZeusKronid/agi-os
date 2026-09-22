import { useId, type ComponentProps, type CSSProperties } from 'react'

import { cn } from '@/shared/lib/cn'

import { ARC_DOTS, buildRays, type SunburstSpec } from './rays'

type SunburstVariant = 'hero' | 'mark' | 'disc' | 'split' | 'live'

const specs: Record<SunburstVariant, SunburstSpec> = {
  // Большой восход над заголовком hero.
  hero: {
    width: 640, height: 246, cx: 320, cy: 236, radius: 155, rays: 96, full: false, seed: 7,
    long: 0.37, shortMin: 0.13, shortMax: 0.27, fade: [1.03, 1.46], strokeWidth: 0.9, farDots: true,
  },
  // Живой восход hero: те же лучи, запас места сверху под лучи, вытянутые курсором и голосом.
  live: {
    width: 640, height: 246, cx: 320, cy: 236, radius: 155, rays: 96, full: false, seed: 7,
    long: 0.37, shortMin: 0.13, shortMax: 0.27, fade: [1.03, 1.85], strokeWidth: 0.9, farDots: true, headroom: 90,
  },
  // Маленький восход над заголовком секции.
  mark: {
    width: 240, height: 98, cx: 120, cy: 92, radius: 60, rays: 40, full: false, seed: 3,
    long: 0.37, shortMin: 0.13, shortMax: 0.27, fade: [1.03, 1.46], strokeWidth: 1, farDots: false,
  },
  // Восход hero, разрезанный швом между карточками Get involved: лучи с запасом длины, без центрального луча.
  split: {
    width: 640, height: 246, cx: 320, cy: 236, radius: 155, rays: 96, full: false, seed: 7,
    long: 0.37, shortMin: 0.13, shortMax: 0.27, fade: [1.03, 1.75], strokeWidth: 1, farDots: false, reach: 1.45,
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
  live: buildRays(specs.live),
  mark: buildRays(specs.mark),
  disc: buildRays(specs.disc),
  split: buildRays(specs.split),
} satisfies Record<SunburstVariant, unknown>

interface SunburstProps extends Omit<ComponentProps<'svg'>, 'children'> {
  variant: SunburstVariant
}

/**
 * Знак-восход: тонкая коралловая дуга с лучами. Декоративный, скрыт от ассистивных технологий.
 *
 * У варианта с `reach` лучи и дуга размечены `pathLength=1` и управляются через `stroke-dashoffset`:
 * в покое луч укорочен до обычной длины, а `--sun-extend: 1` на любом предке вытягивает его целиком
 * волной от зенита к горизонту. Дугу и лучи можно дорисовать анимацией: `[data-sun-arc]`, `[data-sun-ray]`.
 *
 * У варианта с `headroom` (`live`) viewBox продлён вверх, а солнце обрезано по горизонту: оно встаёт
 * из-за линии основания CSS-анимациями, которые ждут на паузе атрибута `data-sun-go` (его ставит
 * `widgets/hero/lib/mount-live-sun.ts`, когда главный поток свободен), а длину лучей потом каждый кадр
 * ведёт JS. Без JS паузу снимает `<noscript>` в hero, и вход играет сразу.
 */
export function Sunburst({ variant, className, ...props }: SunburstProps) {
  const spec = specs[variant]
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const fadeId = `sun-fade-${id}`
  const maskId = `sun-mask-${id}`
  const clipId = `sun-clip-${id}`
  const { cx, cy, radius } = spec
  const reach = spec.reach
  const live = spec.headroom !== undefined
  const top = -(spec.headroom ?? 0)
  const fullHeight = spec.height - top

  const rayLines = rays[variant].map((ray, index) =>
    reach ? (
      <line
        key={index}
        data-sun-ray
        data-sweep={ray.sweep}
        pathLength={1}
        x1={ray.x1}
        y1={ray.y1}
        x2={ray.x2}
        y2={ray.y2}
        strokeOpacity={ray.opacity}
        className="[stroke-dasharray:1_1] [stroke-dashoffset:calc((1_-_var(--sun-extend,0))_*_var(--sun-rest))] transition-[stroke-dashoffset] duration-700 ease-out-strong motion-reduce:transition-none"
        style={
          {
            '--sun-rest': (1 - 1 / reach).toFixed(3),
            transitionDelay: `${Math.round((1 - Number(ray.height)) * 260)}ms`,
          } as CSSProperties
        }
      />
    ) : (
      <line
        key={index}
        x1={ray.x1}
        y1={ray.y1}
        x2={ray.x2}
        y2={ray.y2}
        strokeOpacity={ray.opacity}
        {...(live && {
          // Лучи вырастают от дуги наружу: сначала у зенита, к горизонту позже (как подъём в прототипе).
          'data-sun-ray': true,
          pathLength: 1,
          strokeDasharray: '1 1',
          className: 'motion-safe:animate-sun-ray',
          style: { animationDelay: `${(0.25 + (1 - Number(ray.height)) * 0.6).toFixed(2)}s` },
        })}
      />
    ),
  )

  const arcDots = ARC_DOTS.map((degrees) => {
    const angle = (degrees * Math.PI) / 180
    return (
      <circle
        key={degrees}
        {...(live ? { 'data-sun-dot': true } : {})}
        cx={(cx + radius * Math.cos(angle)).toFixed(1)}
        cy={(cy + radius * Math.sin(angle)).toFixed(1)}
        r={degrees === 180 || degrees === 360 ? 2.4 : 1.6}
      />
    )
  })

  const zenith = (
    <>
      <line x1={cx} y1={cy - radius} x2={cx} y2={(cy - radius * 0.46).toFixed(1)} stroke="currentColor" strokeWidth="1" />
      <circle cx={cx} cy={(cy - radius * 0.43).toFixed(1)} r="2.2" />
    </>
  )

  const farDots = spec.farDots && (
    <>
      <circle cx={cx - 282} cy={cy - 108} r="2" />
      <circle cx={cx + 282} cy={cy - 108} r="2" />
    </>
  )

  const defs = (
    <defs>
      <radialGradient id={fadeId} gradientUnits="userSpaceOnUse" cx={cx} cy={cy} r={radius * spec.fade[1]}>
        <stop offset={(spec.fade[0] / spec.fade[1]).toFixed(2)} stopColor="#fff" />
        <stop offset="1" stopColor="#fff" stopOpacity="0" />
      </radialGradient>
      <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y={top} width={spec.width} height={fullHeight}>
        <rect y={top} width={spec.width} height={fullHeight} fill={`url(#${fadeId})`} />
      </mask>
      {live && (
        <clipPath id={clipId}>
          <rect y={top} width={spec.width} height={cy - top} />
        </clipPath>
      )}
    </defs>
  )

  if (live) {
    return (
      <svg
        viewBox={`0 ${top} ${spec.width} ${fullHeight}`}
        fill="none"
        stroke="currentColor"
        aria-hidden="true"
        data-sun-live
        data-cx={cx}
        data-cy={cy}
        data-r={radius}
        // Вход стоит на паузе, пока JS не поставит `data-sun-go` (страница освободилась после гидрации).
        className={cn('overflow-visible [&:not([data-sun-go])_*]:[animation-play-state:paused]', className)}
        {...props}
      >
        {defs}
        {/* Горизонт — основание дуги: всё солнце обрезано по нему и встаёт из-за заголовка. */}
        <g clipPath={`url(#${clipId})`}>
          <g className="motion-safe:animate-sun-rise">
            <g mask={`url(#${maskId})`} strokeWidth={spec.strokeWidth}>
              {rayLines}
            </g>
            <path
              d={`M${cx - radius} ${cy}A${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`}
              strokeWidth="1.5"
              pathLength={1}
              strokeDasharray="1 1"
              className="motion-safe:animate-sun-arc"
            />
            <g fill="currentColor" stroke="none" className="motion-safe:animate-sun-late">
              {zenith}
              {arcDots}
            </g>
          </g>
        </g>
        <g fill="currentColor" stroke="none" className="motion-safe:animate-sun-late">
          {farDots}
        </g>
      </svg>
    )
  }

  return (
    <svg
      viewBox={`0 0 ${spec.width} ${spec.height}`}
      fill="none"
      stroke="currentColor"
      aria-hidden="true"
      className={className}
      {...props}
    >
      {defs}

      <g mask={`url(#${maskId})`} strokeWidth={spec.strokeWidth}>
        {rayLines}
      </g>

      <g strokeWidth="1.5">
        {spec.full ? (
          <circle cx={cx} cy={cy} r={radius} />
        ) : (
          <path
            d={`M${cx - radius} ${cy}A${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`}
            {...(reach ? { 'data-sun-arc': true, pathLength: 1, strokeDasharray: '1 1' } : {})}
          />
        )}
      </g>

      {!spec.full && (
        <g fill="currentColor" stroke="none">
          {!reach && zenith}
          {arcDots}
          {farDots}
        </g>
      )}
    </svg>
  )
}
