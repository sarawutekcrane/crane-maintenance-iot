/**
 * R8 PRE-UAT (Owner Decision 2) — TEST repair classification client (TEST-CANDIDATE-R1
 * subset of the Owner workbook; never REAL). The backend validates every code fail-closed.
 */
import { apiGet, type ApiResult } from './apiClient'
import { preuatSend } from './masterRecords'
import type { ClassificationRow, RepairCatalogue, RepairClassification } from './types'

export function getRepairCatalogue(): Promise<ApiResult<RepairCatalogue>> {
  return apiGet<RepairCatalogue>('/repair-classification/catalogue')
}

export function getRepairClassification(repairId: string): Promise<ApiResult<RepairClassification>> {
  return apiGet<RepairClassification>(`/repairs/${encodeURIComponent(repairId)}/classification`)
}

export function stageClassification(repairId: string, expectedRevision: number, rows: ClassificationRow[],
  requestId: string): Promise<ApiResult<RepairClassification>> {
  const clean = rows.map((r) => ({ system: r.system, assembly: r.assembly, point: r.point, symptoms: r.symptoms,
    actions: r.actions, position: r.position, ...(r.note ? { note: r.note } : {}) }))
  return preuatSend<RepairClassification>(`/repairs/${encodeURIComponent(repairId)}/classification-drafts`, 'POST',
    { expected_revision: expectedRevision, rows: clean }, requestId)
}

export function finalizeClassification(repairId: string, expectedRevision: number,
  requestId: string): Promise<ApiResult<RepairClassification>> {
  return preuatSend<RepairClassification>(`/repairs/${encodeURIComponent(repairId)}/classification-finalizations`,
    'POST', { expected_revision: expectedRevision }, requestId)
}
