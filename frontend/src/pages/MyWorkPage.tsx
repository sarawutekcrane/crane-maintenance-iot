import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ErrorState } from '../components/ErrorState'
import { LoadingState } from '../components/LoadingState'
import { ResponsiveTable } from '../components/ResponsiveTable'
import { StatusBadge } from '../components/StatusBadge'
import { ApiError, apiGet } from '../lib/apiClient'
import {
  assetTypeLabel,
  describeErrorCode,
  formatThaiDateTime,
  repairSourceTypeLabel,
  repairStatusLabel,
  repairStatusTone,
} from '../lib/labels'
import type { Page, RepairSummary } from '../lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string; requestId?: string | null }
  | { kind: 'ready'; items: RepairSummary[] }

/**
 * "งานของฉัน" (Core Demo Fixes prompt, REPAIR WORKFLOW CORRECTIONS section
 * C) — OPEN repairs assigned (as primary technician or collaborator) to
 * the current application actor/user context. Backend resolves "current
 * actor" from RequestContext (dev-safe capability gate, not production
 * auth) via GET /repairs/my-work.
 */
export function MyWorkPage() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    const result = await apiGet<Page<RepairSummary>>('/repairs/my-work?page_size=50')
    if (!result.ok) {
      const err = result.error
      setState({
        kind: 'error',
        message: err instanceof ApiError ? describeErrorCode(err.code) : err.message,
        requestId: err instanceof ApiError ? err.requestId : null,
      })
      return
    }
    setState({ kind: 'ready', items: result.data.items })
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <section className="page">
      <h1>งานของฉัน</h1>
      <p>ใบแจ้งซ่อมที่กำลังดำเนินการ (OPEN) ซึ่งได้รับมอบหมายให้ฉันเป็นช่างหลักหรือผู้ร่วมงาน</p>

      {state.kind === 'loading' && <LoadingState message="กำลังโหลดงานของฉัน..." />}
      {state.kind === 'error' && (
        <ErrorState message={state.message} requestId={state.requestId} onRetry={load} />
      )}

      {state.kind === 'ready' && (
        <ResponsiveTable
          columns={[
            {
              key: 'opened_at',
              header: 'วันที่แจ้งซ่อม',
              render: (row) => (
                <Link to={`/repairs/${row.repair_id}`}>{formatThaiDateTime(row.opened_at)}</Link>
              ),
            },
            {
              key: 'asset',
              header: 'สินทรัพย์',
              render: (row) => `${assetTypeLabel[row.asset_type] ?? row.asset_type} ${row.asset_id}`,
            },
            {
              key: 'symptom',
              header: 'อาการ/ปัญหาที่พบ',
              render: (row) => row.symptom ?? '-',
            },
            {
              key: 'source',
              header: 'แหล่งที่มา',
              render: (row) => repairSourceTypeLabel[row.source_type] ?? row.source_type,
            },
            {
              key: 'status',
              header: 'สถานะ',
              render: (row) => (
                <StatusBadge
                  label={repairStatusLabel[row.status] ?? row.status}
                  tone={repairStatusTone[row.status]}
                />
              ),
            },
          ]}
          rows={state.items}
          getRowKey={(row) => row.repair_id}
          emptyTitle="ยังไม่มีงานที่มอบหมายให้ฉัน"
          emptyDescription="เมื่อได้รับมอบหมายใบแจ้งซ่อมที่ยังไม่ปิดงาน รายการจะแสดงที่นี่"
        />
      )}
    </section>
  )
}
