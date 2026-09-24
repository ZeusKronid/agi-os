import { useCallback, useEffect, useState } from 'react'

import { detectOs } from '../lib/detect-os'
import type { OsId, StepId, TargetId } from './route'

const STORAGE_KEY = 'agios:install-route'

interface RouteState {
  os: OsId
  target: TargetId
  done: Partial<Record<StepId, boolean>>
}

const initialState: RouteState = { os: 'linux', target: 'usb', done: {} }

function readSaved(): RouteState | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    return raw ? { ...initialState, ...(JSON.parse(raw) as Partial<RouteState>) } : null
  } catch {
    return null
  }
}

function save(state: RouteState) {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // Приватный режим или запрет хранилища: маршрут просто не переживёт перезагрузку.
  }
}

/**
 * Выбор системы, носителя и отмеченные шаги. SSR рендерит Linux + USB; после гидрации подставляем
 * сохранённый маршрут, а если его нет — систему посетителя по user agent.
 */
export function useInstallRoute() {
  const [state, setState] = useState<RouteState>(initialState)
  const [detected, setDetected] = useState<OsId | null>(null)

  useEffect(() => {
    const os = detectOs(navigator.userAgent)
    setDetected(os)
    setState(readSaved() ?? { ...initialState, os })
  }, [])

  const update = useCallback((next: (current: RouteState) => RouteState) => {
    setState((current) => {
      const value = next(current)
      save(value)
      return value
    })
  }, [])

  const setOs = useCallback((os: OsId) => update((current) => ({ ...current, os })), [update])
  const setTarget = useCallback((target: TargetId) => update((current) => ({ ...current, target })), [update])
  const setDone = useCallback(
    (step: StepId, done: boolean) => update((current) => ({ ...current, done: { ...current.done, [step]: done } })),
    [update],
  )
  const reset = useCallback(() => update((current) => ({ ...current, done: {} })), [update])

  return { ...state, detected, setOs, setTarget, setDone, reset }
}
