/**
 * R2 Batch R2f-h4 B4 (C1 Amendment A1-§25) — fail-closed parsing of the two
 * read-only server facts on `GET /me`: the V2 cutover flag and the data context.
 * Informational only: never an authorization control, never a local toggle.
 */
import type { MeResponse } from './types'

export type DataContextLabel = 'REAL' | 'TEST' | 'UNCONFIGURED' | 'UNKNOWN'

export interface ServerSignals {
  /** True only when GET /me succeeded AND reported exactly `true`. */
  v2Enabled: boolean
  /** REAL / TEST only when the server reports exactly that; UNCONFIGURED when it
   * says so; UNKNOWN when /me failed or the value is missing / invalid. */
  dataContext: DataContextLabel
  /** False when /me failed or a signal was missing / invalid. */
  ok: boolean
}

export const UNKNOWN_SIGNALS: ServerSignals = { v2Enabled: false, dataContext: 'UNKNOWN', ok: false }

/** Fail-closed parsing of the two /me signals (exported for unit tests). */
export function serverSignalsFrom(me: MeResponse | null): ServerSignals {
  if (!me) return UNKNOWN_SIGNALS
  const flag = me.technician_assignment_v2_enabled
  const context = me.data_context
  const dataContext: DataContextLabel =
    context === 'REAL' || context === 'TEST' || context === 'UNCONFIGURED' ? context : 'UNKNOWN'
  const ok = typeof flag === 'boolean' && dataContext !== 'UNKNOWN'
  return { v2Enabled: ok && flag === true, dataContext, ok }
}
