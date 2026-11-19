/**
 * R8 PRE-UAT (Owner Decision 1) — repair material (Store) workflow client. Future stock
 * integration only: no stock ledger. Every write carries a retained X-Request-Id
 * (`preuatSend`), so a resend replays instead of double-recording; the backend enforces
 * grants, V2 membership and quantity guards.
 */
import { apiGet, type ApiResult } from './apiClient'
import { preuatSend } from './masterRecords'
import type { StoreReconciliation, StoreWriteResult } from './types'

export type StoreLineStep =
  | 'approvals' | 'denials' | 'issues' | 'use-confirmations' | 'return-declarations' | 'return-acceptances'

export interface StoreRequestLineInput {
  part_id?: string
  part_description: string
  /** Decimal text (at most 3 places), sent as typed: the backend parses it without float rounding. */
  quantity: string
  unit: string
}

export function getStoreReconciliation(repairId: string): Promise<ApiResult<StoreReconciliation>> {
  return apiGet<StoreReconciliation>(`/repairs/${encodeURIComponent(repairId)}/store-reconciliation`)
}

export function createStoreRequest(repairId: string, lines: StoreRequestLineInput[], requestId: string,
  note?: string): Promise<ApiResult<StoreWriteResult>> {
  return preuatSend<StoreWriteResult>(`/repairs/${encodeURIComponent(repairId)}/store-requests`, 'POST',
    note ? { lines, note } : { lines }, requestId)
}

export function storeLineStep(repairId: string, lineId: string, step: StoreLineStep, body: Record<string, unknown>,
  requestId: string): Promise<ApiResult<StoreWriteResult>> {
  return preuatSend<StoreWriteResult>(
    `/repairs/${encodeURIComponent(repairId)}/store-lines/${encodeURIComponent(lineId)}/${step}`, 'POST', body,
    requestId)
}
