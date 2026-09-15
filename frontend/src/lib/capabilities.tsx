import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { apiGet } from './apiClient'
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
}

const CapabilitiesContext = createContext<CapabilitiesState>({
  capabilities: new Set(),
  loading: true,
  userId: null,
})

export function CapabilitiesProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<CapabilitiesState>({
    capabilities: new Set(),
    loading: true,
    userId: null,
  })

  useEffect(() => {
    let cancelled = false
    void apiGet<MeResponse>('/me').then((result) => {
      if (cancelled) return
      if (result.ok) {
        setState({
          capabilities: new Set(result.data.capabilities),
          loading: false,
          userId: result.data.user_id,
        })
      } else {
        setState({ capabilities: new Set(), loading: false, userId: null })
      }
    })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <CapabilitiesContext.Provider value={state}>{children}</CapabilitiesContext.Provider>
  )
}

export function useCapabilities() {
  const { capabilities, loading, userId } = useContext(CapabilitiesContext)
  return {
    loading,
    userId,
    hasCapability: (capability: string) => capabilities.has(capability),
  }
}
