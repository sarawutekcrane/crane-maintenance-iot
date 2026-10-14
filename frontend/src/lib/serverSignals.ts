/**
 * R2 Batch R2f-h4 B4 (C1 Amendment A1-§25) — fail-closed parsing of the
 * read-only server data context on `GET /me`. Informational only: never an
 * authorization control, never a local toggle.
 *
 * R2 Batch R2f-h4 B6 Rev2 (owner final decision: Technician V2 only): the former
 * V2 cutover flag is gone from the server and from here; nothing in the
 * frontend depends on a V2 ON/OFF state.
 */
import type { MeResponse } from './types'

export type DataContextLabel = 'REAL' | 'TEST' | 'UNCONFIGURED' | 'UNKNOWN'

export interface ServerSignals {
  /** REAL / TEST only when the server reports exactly that; UNCONFIGURED when it
   * says so; UNKNOWN when /me failed or the value is missing / invalid. */
  dataContext: DataContextLabel
  /** False when /me failed or the data context was missing / invalid. */
  ok: boolean
}

export const UNKNOWN_SIGNALS: ServerSignals = { dataContext: 'UNKNOWN', ok: false }

/** Fail-closed parsing of the /me data context (exported for unit tests). */
export function serverSignalsFrom(me: MeResponse | null): ServerSignals {
  if (!me) return UNKNOWN_SIGNALS
  const context = me.data_context
  const dataContext: DataContextLabel =
    context === 'REAL' || context === 'TEST' || context === 'UNCONFIGURED' ? context : 'UNKNOWN'
  return { dataContext, ok: dataContext !== 'UNKNOWN' }
}
