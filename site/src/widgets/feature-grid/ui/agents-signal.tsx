import { useId, type CSSProperties } from 'react'

import { AgentIcon } from '@/entities/agent'
import { cn } from '@/shared/lib/cn'
import { Logo } from '@/shared/ui/logo'
import { buildRays, type SunburstSpec } from '@/shared/ui/sunburst'

import { mountAgentSignal } from '../lib/mount-agent-signal'
import { SCENE, SIGNAL_NODES, SIGNAL_ORDER } from '../model/agent-signal'

// Полный диск-восход в координатах сцены: те же пропорции, что у варианта `disc` в `shared/ui/sunburst`,
// но лучи рисуются здесь, чтобы разгораться в сторону активного агента по одному.
const DISC: SunburstSpec = {
  width: SCENE.width, height: SCENE.height, cx: SCENE.cx, cy: SCENE.cy, radius: SCENE.discRadius, rays: SCENE.rays,
  full: true, seed: 5, long: 0.6, shortMin: 0.2, shortMax: 0.42, fade: [1.05, 1.75], strokeWidth: 1, farDots: false,
}
const RAYS = buildRays(DISC)

const FIRST = SIGNAL_NODES.find((node) => node.id === SIGNAL_ORDER[0]) ?? SIGNAL_NODES[0]!

const percent = (value: number, total: number) => `${((value / total) * 100).toFixed(2)}%`

/**
 * Сцена «Сигнал»: восход в центре, агенты как звёзды вокруг, линия связи всегда ведёт к одному из них.
 * Разметка SSR уже подключена к первому агенту; движение добавляет `mountAgentSignal`.
 * Визуал декоративный (`aria-hidden` у карточки), поэтому узлы — не кнопки: имена агентов есть в ленте выше и в FAQ.
 */
export function AgentsSignalVisual() {
  const id = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const fadeId = `signal-fade-${id}`
  const maskId = `signal-mask-${id}`

  return (
    <div ref={mountAgentSignal} className="absolute inset-0 cursor-default">
      <div data-signal-scene="" className="absolute inset-0 m-auto aspect-[6/5] w-full max-w-[360px]">
        <svg
          viewBox={`0 0 ${SCENE.width} ${SCENE.height}`}
          fill="none"
          className="absolute inset-0 size-full text-accent"
        >
          <defs>
            <radialGradient
              id={fadeId}
              gradientUnits="userSpaceOnUse"
              cx={SCENE.cx}
              cy={SCENE.cy}
              r={(DISC.radius * DISC.fade[1]).toFixed(1)}
            >
              <stop offset={(DISC.fade[0] / DISC.fade[1]).toFixed(2)} stopColor="#fff" />
              <stop offset="1" stopColor="#fff" stopOpacity="0" />
            </radialGradient>
            <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width={SCENE.width} height={SCENE.height}>
              <rect width={SCENE.width} height={SCENE.height} fill={`url(#${fadeId})`} />
            </mask>
          </defs>

          {/* Кольца сигнала: расходятся от ядра, под reduced motion не появляются вовсе. */}
          {[0, 1.3].map((delay) => (
            <circle
              key={delay}
              cx={SCENE.cx}
              cy={SCENE.cy}
              r="38"
              vectorEffect="non-scaling-stroke"
              stroke="currentColor"
              strokeWidth="1"
              className="origin-center opacity-0 [transform-box:fill-box] motion-safe:animate-ripple"
              style={{ animationDelay: `${delay}s` }}
            />
          ))}

          <line
            data-signal-link=""
            x1={SCENE.cx}
            y1={SCENE.cy}
            x2={FIRST.x}
            y2={FIRST.y}
            stroke="currentColor"
            strokeWidth="1"
            strokeLinecap="round"
            className="opacity-90"
          />
          <circle data-signal-dot="" cx={FIRST.x} cy={FIRST.y} r="2.4" fill="currentColor" className="opacity-90" />

          <g
            data-signal-rays=""
            mask={`url(#${maskId})`}
            stroke="currentColor"
            strokeWidth={DISC.strokeWidth}
            className="[&_line]:transition-opacity [&_line]:duration-300"
          >
            {/* Базовая яркость луча — через `--ray`, чтобы `mountAgentSignal` мог поднять активные до 1 инлайн-стилем и вернуть обратно. */}
            {RAYS.map((ray, index) => (
              <line
                key={index}
                x1={ray.x1}
                y1={ray.y1}
                x2={ray.x2}
                y2={ray.y2}
                style={{ '--ray': (Number(ray.opacity) * 0.55).toFixed(2) } as CSSProperties}
                className="opacity-(--ray)"
              />
            ))}
          </g>
          <circle cx={SCENE.cx} cy={SCENE.cy} r={DISC.radius} stroke="currentColor" strokeWidth="1.5" className="fill-canvas" />
        </svg>

        <div className="pointer-events-none absolute top-1/2 left-1/2 grid size-16 -translate-x-1/2 -translate-y-1/2 place-items-center text-accent">
          <Logo className="h-auto w-[34px]" />
        </div>

        {SIGNAL_NODES.map((node) => (
          <span
            key={node.id}
            data-signal-node={node.id}
            data-on={node.id === FIRST.id}
            style={{ left: percent(node.x, SCENE.width), top: percent(node.y, SCENE.height), width: node.size, height: node.size }}
            className={cn(
              'absolute z-[2] grid -translate-x-1/2 -translate-y-1/2 place-items-center rounded-[32%] bg-surface text-ink-soft inset-ring inset-ring-line',
              'transition-[box-shadow,color,scale,background-color] duration-250 ease-out-strong',
              'data-[on=true]:scale-[1.06] data-[on=true]:bg-elevated data-[on=true]:text-ink data-[on=true]:inset-ring-accent motion-reduce:data-[on=true]:scale-100',
              '[&_svg]:size-1/2',
            )}
          >
            <AgentIcon mark={node.agent.mark} />
            {node.local && (
              <i className="absolute top-[calc(100%+5px)] left-1/2 -translate-x-1/2 font-mono text-[9.5px] tracking-[0.14em] text-ink-dim uppercase not-italic">
                local
              </i>
            )}
          </span>
        ))}
      </div>

      <span
        data-signal-status=""
        data-swap="false"
        className="group/status absolute top-3.5 left-3.5 z-[3] inline-flex h-7 max-w-[calc(100%-28px)] items-center gap-[7px] rounded-full bg-raised px-3 font-mono text-[11.5px] tracking-[0.04em] text-ink-muted"
      >
        <i className="size-[7px] shrink-0 rounded-full bg-accent" />
        <span className="truncate transition-[opacity,filter] duration-200 group-data-[swap=true]/status:opacity-0 group-data-[swap=true]/status:blur-[2px]">
          <b data-signal-name="" className="font-medium text-ink">
            {FIRST.agent.label}
          </b>
          {' · '}
          <span data-signal-auth="">{FIRST.auth}</span>
        </span>
      </span>
    </div>
  )
}
