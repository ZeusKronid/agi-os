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

/** Детерминированный шум 0..1: одинаковый на сервере и клиенте. */
const noise = (index: number, salt: number) => {
  const x = Math.sin(index * 12.9898 + salt * 78.233) * 43758.5453
  return x - Math.floor(x)
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
 * Вариант с `headroom` (`live`) — HTML-обёртка, обрезанная по горизонту: лучи-полоски, дуга в поворотном
 * окне и SVG с точками. Он встаёт из-за линии основания с первой отрисовки на композиторных анимациях,
 * а длину лучей потом каждый кадр ведёт JS (`mount-live-sun.ts` рядом).
 * Без JS это законченный статичный восход.
 */
export function Sunburst({ variant, className, ...props }: SunburstProps) {
  const spec = specs[variant]
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const fadeId = `sun-fade-${id}`
  const maskId = `sun-mask-${id}`
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
    </defs>
  )

  if (live) {
    const view = `0 ${top} ${spec.width} ${fullHeight}`
    // Длина в единицах viewBox → CSS: обёртка — контейнер, 100cqw = ширина восхода.
    const unit = (value: number) => `calc(${value.toFixed(2)} * 100cqw / ${spec.width})`
    const horizon = `${(((cy - top) / fullHeight) * 100).toFixed(3)}%`
    return (
      // Обёртка обрезает всё по горизонту (основание дуги): солнце встаёт из-за заголовка.
      // Вход повторяет прототип, но собран только из transform/opacity HTML-слоёв — их ведёт композитор,
      // поэтому гидрация и длинные задачи главного потока его не замораживают.
      <div
        data-sun-live
        data-center={(cx / spec.width).toFixed(4)}
        data-units={spec.width}
        aria-hidden="true"
        className={cn('@container relative overflow-hidden', className)}
        style={{ aspectRatio: `${spec.width} / ${cy - top}` }}
      >
        <div
          className="absolute inset-x-0 top-0 motion-safe:animate-sun-rise"
          style={{ aspectRatio: `${spec.width} / ${fullHeight}` }}
        >
          {/* Лучи — полоски от дуги наружу. Каждая растёт через scaleX со своей задержкой: сначала у зенита,
              к горизонту позже и дольше (как рост лучей вслед за подъёмом в прототипе). Сияние идёт уже
              во время роста и не меняется потом: луч вразнобой удлиняется и укорачивается по формуле
              голоса из прототипа (свойство `scale`) — с первой отрисовки, не дожидаясь JS и демо. Затухание к концу луча — градиент самой
              полоски (у SVG это делала радиальная маска). */}
          <div
            data-sun-rays
            className="absolute"
            style={{ left: `${((cx / spec.width) * 100).toFixed(3)}%`, top: horizon }}
          >
            {rays[variant].map((ray, index) => {
              const x1 = Number(ray.x1) - cx
              const y1 = Number(ray.y1) - cy
              const inner = Math.hypot(x1, y1)
              const length = Math.hypot(Number(ray.x2) - cx, Number(ray.y2) - cy) - inner
              const angle = Math.atan2(y1, x1)
              const fromZenith = 1 - Number(ray.height)
              const delay = 0.25 + 0.17 * fromZenith
              // Сияние по формуле голоса из прототипа: у луча своя доля голоса (0.4–1.3), луч удлиняется
              // на 0.7 × доля и быстро мерцает между 65% и 100% этого удлинения (полный цикл ~0.57 с).
              const share = 0.4 + 0.9 * noise(index, 1)
              const flicker = 0.26 + 0.06 * noise(index, 2)
              const timing = {
                '--ray-delay': `${delay.toFixed(3)}s`,
                '--ray-duration': `${(0.45 + 1.2 * fromZenith ** 3).toFixed(3)}s`,
                '--shimmer-low': (1 + 0.7 * share * 0.65).toFixed(3),
                '--shimmer-high': (1 + 0.7 * share).toFixed(3),
                '--shimmer-duration': `${flicker.toFixed(3)}s`,
                // Отрицательная задержка: луч уже посреди своего цикла — растёт неровным и мерцает
                // с первых кадров входа, одинаково до и после того, как дорисуется дуга.
                '--shimmer-delay': `${(-2 * flicker * noise(index, 3)).toFixed(3)}s`,
              } as CSSProperties
              // Линзу и голос (`mount-live-sun.ts`) JS ведёт через transform и opacity этой обёртки, а не через
              // ширину полоски: на полоске крутятся CSS-анимации роста и сияния, и запись в её стиль каждый кадр
              // стоила пересчёта стилей и раскладки всех лучей.
              return (
                <div
                  key={index}
                  data-sun-ray
                  data-angle={angle.toFixed(4)}
                  data-inner={inner.toFixed(2)}
                  data-opacity={ray.opacity}
                  className="absolute top-0 left-0"
                  style={{ rotate: `${angle.toFixed(4)}rad`, opacity: ray.opacity }}
                >
                  <i
                    className="absolute top-0 block origin-left motion-safe:animate-sun-ray"
                    style={{
                      left: unit(inner),
                      width: unit(length),
                      // Не тоньше 1px: на узком восходе полоска в 0,5px почти не рисуется (SVG-линии так не пропадали).
                      height: `max(1px, ${unit(spec.strokeWidth)})`,
                      marginTop: `calc(max(1px, ${unit(spec.strokeWidth)}) / -2)`,
                      backgroundImage: `linear-gradient(90deg, currentColor ${unit(Math.max(0, radius * spec.fade[0] - inner))}, transparent ${unit(radius * spec.fade[1] - inner)})`,
                      ...timing,
                    }}
                  />
                </div>
              )
            })}
          </div>
          {/* Дуга рисуется вдоль себя: окно-полуплоскость поворачивается вокруг центра солнца от горизонта
              слева к горизонту справа, а дуга внутри вращается навстречу и стоит на месте. */}
          <div
            className="absolute inset-x-0 h-full origin-top overflow-hidden rotate-180 motion-safe:animate-sun-sweep"
            style={{ top: horizon }}
          >
            <svg
              viewBox={view}
              fill="none"
              stroke="currentColor"
              className="absolute inset-x-0 block h-full w-full -rotate-180 motion-safe:animate-sun-unsweep"
              style={{ top: `-${horizon}`, transformOrigin: `50% ${horizon}` }}
            >
              <path d={`M${cx - radius} ${cy}A${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`} strokeWidth="1.5" />
            </svg>
          </div>
          <svg
            viewBox={view}
            fill="currentColor"
            stroke="none"
            className="absolute inset-0 block size-full motion-safe:animate-sun-late"
          >
            {zenith}
            {arcDots}
            {farDots}
          </svg>
        </div>
      </div>
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
