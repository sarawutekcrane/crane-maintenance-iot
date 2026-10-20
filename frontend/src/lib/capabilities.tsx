import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { apiGet } from './apiClient'
import { UNKNOWN_SIGNALS, serverSignalsFrom, type ServerSignals } from './serverSignals'
import type { MeResponse } from './types'

/**
 * Core Demo Fixes Delta REV05 section 10: capability-driven nav/action
 * visibility instead of a hard-coded "Driver sees pages X/Y/Z" matrix.
 * This is a UX convenience only — every write action is re-checked by
 * the backend (`app.domain.authz.require_capability`) regardless of what
 * this hook reports, so a stale/optimistic value here is never a
 * security concern, only a display one.
 */
interface CapabilitiesState {
  capabilities: Set<string>
  loading: boolean
  /** Final Cross-Phase Integration Fix (F5): the current actor's own
   * `user_id`, from the same `/me` call — lets a page show an
   * assignment-aware control (e.g. "is this technician the one actively
   * assigned?") without inventing a second, frontend-only source of
   * truth. Purely a display/UX convenience; the backend re-checks actual
   * assignment on every write regardless of what this reports. */
  userId: string | null
  /** R2 Batch R2f-h4 B4 (A1-§25): the server's V2 cutover flag and data
   * context, parsed fail-closed. Informational only — never an
   * authorization control, never a frontend-local toggle. */
  signals: ServerSignals
}

interface CapabilitiesContextValue extends CapabilitiesState {
  /** Access Management: re-read `/me` (after a permission save, or when the
   * window regains focus) so a granted or revoked permission shows without a
   * new login. The backend already enforces the change on the next request. */
  refresh: () => void
}

const CapabilitiesContext = createContext<CapabilitiesContextValue>({
  capabilities: new Set(),
  loading: true,
  userId: null,
  signals: UNKNOWN_SIGNALS,
  refresh: () => {},
})

export function CapabilitiesProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<CapabilitiesState>({
    capabilities: new Set(),
    loading: true,
    userId: null,
    signals: UNKNOWN_SIGNALS,
  })

  const [generation, setGeneration] = useState(0)
  const refresh = useCallback(() => setGeneration((g) => g + 1), [])

  useEffect(() => {
    let cancelled = false
    void apiGet<MeResponse>('/me').then((result) => {
      if (cancelled) return
      if (result.ok) {
        setState({
          capabilities: new Set(result.data.capabilities),
          loading: false,
          userId: result.data.user_id,
          signals: serverSignalsFrom(result.data),
        })
      } else {
        setState({ capabilities: new Set(), loading: false, userId: null, signals: UNKNOWN_SIGNALS })
      }
    })
    return () => {
      cancelled = true
    }
  }, [generation])

  useEffect(() => {
    window.addEventListener('focus', refresh)
    return () => window.removeEventListener('focus', refresh)
  }, [refresh])

  return (
    <CapabilitiesContext.Provider value={{ ...state, refresh }}>{children}</CapabilitiesContext.Provider>
  )
}

export function useCapabilities() {
  const { capabilities, loading, userId, signals, refresh } = useContext(CapabilitiesContext)
  return {
    loading,
    refresh,
    userId,
    signals,
    hasCapability: (capability: string) => capabilities.has(capability),
  }
}
