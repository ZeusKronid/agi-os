import { useCallback, useEffect, useState } from 'react'

import { track } from '@/shared/lib/analytics'

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

  // События — только на действия посетителя: автоопределение системы после гидрации их не шлёт.
  const setOs = useCallback(
    (os: OsId) => {
      track('install_os', { os, detected: detected ?? 'unknown' })
      update((current) => ({ ...current, os }))
    },
    [update, detected],
  )
  const setTarget = useCallback(
    (target: TargetId) => {
      track('install_target', { target })
      update((current) => ({ ...current, target }))
    },
    [update],
  )
  const setDone = useCallback(
    (step: StepId, done: boolean) => {
      // `onDone` шагов срабатывает повторно (клик, каждая правка совпавшего хэша) — считаем только первый раз.
      if (done && !state.done[step]) track('install_step', { step, os: state.os, target: state.target })
      update((current) => ({ ...current, done: { ...current.done, [step]: done } }))
    },
    [update, state],
  )
  const reset = useCallback(() => update((current) => ({ ...current, done: {} })), [update])

  return { ...state, detected, setOs, setTarget, setDone, reset }
}
