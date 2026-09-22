import { agents, type Agent } from '@/entities/agent'

/** Координатная система сцены «Сигнал»: 360×300, восход в центре. Узлы и SVG считаются в этих единицах. */
export const SCENE = { width: 360, height: 300, cx: 180, cy: 150, discRadius: 34, rays: 72 } as const

/** Как агент подключается: из FAQ «Which agents can I connect?». */
const AUTH = {
  chatgpt: 'sign-in',
  claude: 'sign-in',
  anthropic: 'api key',
  'openai-api': 'api key',
  gemini: 'api key',
  ollama: 'local',
  compatible: 'endpoint',
} as const satisfies Record<string, string>

type SignalAgentId = keyof typeof AUTH

interface NodeSpec {
  id: SignalAgentId
  x: number
  y: number
  size: number
  /** Локальная модель стоит внутри поля лучей: расстояние несёт смысл. */
  local?: true
}

export interface SignalNode extends NodeSpec {
  agent: Agent
  auth: string
  /** Угол от центра к узлу, радианы; по нему разгораются лучи восхода. */
  angle: number
}

const SPECS: readonly NodeSpec[] = [
  { id: 'ollama', x: 254, y: 98, size: 38, local: true },
  { id: 'claude', x: 96, y: 78, size: 40 },
  { id: 'chatgpt', x: 300, y: 194, size: 38 },
  { id: 'anthropic', x: 72, y: 218, size: 34 },
  { id: 'gemini', x: 180, y: 266, size: 34 },
  { id: 'openai-api', x: 322, y: 74, size: 30 },
  { id: 'compatible', x: 38, y: 138, size: 30 },
]

const byId = new Map(agents.map((agent) => [agent.id, agent]))

export const SIGNAL_NODES: readonly SignalNode[] = SPECS.map((spec) => {
  const agent = byId.get(spec.id)
  if (!agent) throw new Error(`Unknown agent "${spec.id}" in agent-signal scene`)
  return { ...spec, agent, auth: AUTH[spec.id], angle: Math.atan2(spec.y - SCENE.cy, spec.x - SCENE.cx) }
})

/** Порядок автообхода: начинаем с Claude, заканчиваем совместимым эндпоинтом. */
export const SIGNAL_ORDER: readonly SignalAgentId[] = [
  'claude',
  'ollama',
  'openai-api',
  'chatgpt',
  'anthropic',
  'gemini',
  'compatible',
]

/** Угол i-го луча диска: та же формула, что в `buildRays` для полного круга. */
export function rayAngle(index: number): number {
  return Math.PI + (Math.PI * 2 * index) / SCENE.rays
}

/** Кратчайшая угловая разница двух направлений. */
export function angleBetween(a: number, b: number): number {
  const delta = Math.abs(a - b) % (Math.PI * 2)
  return Math.min(delta, Math.PI * 2 - delta)
}
